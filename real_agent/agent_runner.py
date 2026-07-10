"""
agent_runner.py
================
LangChain + Ollama SQL agent with sqlglot lineage interception.

In --llm mode the agent:
  1. Receives a natural-language question.
  2. Uses Ollama (local LLM) to generate a SQL query.
  3. Executes the SQL on the Northwind SQLite database.
  4. sqlglot intercepts the executed SQL and extracts table-column lineage.
  5. Builds an AMU from the extracted lineage (no manual self-reporting).
  6. Runs the lineage gate and returns the result.

In demo mode (no Ollama) the same pipeline runs with pre-defined SQL queries,
demonstrating that the sqlglot→AMU→gate machinery works independently of the LLM.

Requirements (LLM mode only):
  pip install langchain langchain-community langchain-ollama
  # and Ollama running with a pulled model, e.g.:
  #   ollama pull llama3.2:3b
"""

from __future__ import annotations

import os
import sqlite3
import textwrap
import time
from typing import Any, Dict, List, Optional, Tuple

from .lineage_extractor import extract_lineage_from_sql, lineage_summary
from .amu_bridge import NorthwindAMU, NorthwindLineageSystem, sql_to_amu
from .northwind_schema import NORTHWIND_PERMISSIONS, NORTHWIND_SENSITIVE


# ---------------------------------------------------------------------------
# SQL execution helper with lineage capture
# ---------------------------------------------------------------------------

class SQLExecutor:
    """
    Wraps a SQLite connection. Records every SELECT query that runs through it
    so the calling code can retrieve the last executed SQL for lineage extraction.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self.last_sql: Optional[str] = None
        self.last_rows: List[Any] = []
        self.last_columns: List[str] = []

    def connect(self):
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self):
        if self._conn:
            self._conn.close()

    def run(self, sql: str) -> Tuple[List[sqlite3.Row], List[str]]:
        """Execute *sql* and capture it for lineage extraction."""
        self.last_sql = sql
        cur = self._conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        self.last_columns = [desc[0] for desc in cur.description] if cur.description else []
        self.last_rows = rows
        return rows, self.last_columns

    def run_and_format(self, sql: str, max_rows: int = 20) -> str:
        """Execute and return human-readable result string."""
        rows, cols = self.run(sql)
        if not rows:
            return "(no rows returned)"
        header = " | ".join(cols)
        separator = "-" * len(header)
        lines = [header, separator]
        for row in rows[:max_rows]:
            lines.append(" | ".join(str(v) for v in row))
        if len(rows) > max_rows:
            lines.append(f"... ({len(rows) - max_rows} more rows)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM-backed SQL Agent (requires langchain + langchain-ollama + Ollama)
# ---------------------------------------------------------------------------

class OllamaSQLAgent:
    """
    LangChain SQL agent backed by a local Ollama model.

    Uses a custom SQL execution wrapper so every query executed by the
    LangChain tool is captured for sqlglot lineage extraction.

    Usage:
        agent = OllamaSQLAgent(db_path, model="llama3.2:3b")
        sql, rows, lineage_steps = agent.query("What is revenue by category?")
    """

    def __init__(
        self,
        db_path: str,
        model: str = "llama3.2:3b",
        base_url: str = "http://localhost:11434",
        verbose: bool = False,
    ):
        self.db_path = db_path
        self.model = model
        self.base_url = base_url
        self.verbose = verbose
        self._agent = None
        self._db_wrapper = None
        self._captured_sqls: List[str] = []

    def _build_agent(self):
        """Lazy-build the LangChain agent (imports happen here to avoid
        ImportError when running in demo mode without langchain installed)."""
        try:
            from langchain_ollama import ChatOllama
            from langchain_community.utilities import SQLDatabase
            from langchain_community.agent_toolkits import create_sql_agent
            from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
            from langchain_core.callbacks import BaseCallbackHandler
        except ImportError as e:
            raise ImportError(
                f"LangChain packages not installed: {e}\n"
                "Install with: pip install langchain langchain-community langchain-ollama"
            ) from e

        class SQLCaptureCallback(BaseCallbackHandler):
            """Captures every SQL string executed by the SQL tool."""
            def __init__(self, capture_list):
                self._cap = capture_list

            def on_tool_start(self, serialized, input_str, **kwargs):
                # The SQLDatabaseToolkit executes via QuerySQLDataBaseTool
                tool_name = serialized.get("name", "")
                if "query" in tool_name.lower() or "sql" in tool_name.lower():
                    if isinstance(input_str, str) and input_str.strip().upper().startswith("SELECT"):
                        self._cap.append(input_str.strip())

        llm = ChatOllama(
            model=self.model,
            base_url=self.base_url,
            temperature=0,
        )

        db = SQLDatabase.from_uri(f"sqlite:///{self.db_path}")

        self._db_wrapper = db
        self._agent = create_sql_agent(
            llm=llm,
            db=db,
            verbose=self.verbose,
            agent_type="zero-shot-react-description",
        )
        self._callback = SQLCaptureCallback(self._captured_sqls)

    def query(self, question: str) -> Tuple[Optional[str], str, List[Dict]]:
        """
        Run the LangChain SQL agent on *question*.

        Returns
        -------
        (last_sql, answer_text, lineage_steps)
          last_sql      : The last SELECT SQL the agent executed (or None)
          answer_text   : The agent's natural-language answer
          lineage_steps : Output of extract_lineage_from_sql on last_sql
        """
        if self._agent is None:
            self._build_agent()

        self._captured_sqls.clear()

        result = self._agent.invoke(
            {"input": question},
            config={"callbacks": [self._callback]},
        )

        answer = result.get("output", str(result))
        last_sql = self._captured_sqls[-1] if self._captured_sqls else None
        lineage_steps = extract_lineage_from_sql(last_sql) if last_sql else []

        return last_sql, answer, lineage_steps


# ---------------------------------------------------------------------------
# Department Agent — orchestrates LLM/demo query + AMU gate logic
# ---------------------------------------------------------------------------

class DepartmentAgent:
    """
    Represents one department's AI agent.

    In demo mode: executes pre-defined SQL, extracts lineage via sqlglot,
                  builds AMU, runs gate.
    In LLM mode:  same pipeline but SQL is generated by Ollama.
    """

    def __init__(
        self,
        department: str,
        executor: SQLExecutor,
        memory: NorthwindLineageSystem,
        epoch_counter: List[int],
        llm_agent: Optional[OllamaSQLAgent] = None,
        verbose: bool = True,
    ):
        self.department = department
        self.executor = executor
        self.memory = memory
        self._epoch = epoch_counter  # shared mutable list so all agents share epoch
        self.llm_agent = llm_agent
        self.verbose = verbose
        self.permitted = NORTHWIND_PERMISSIONS.get(department, set())

    def _next_epoch(self) -> int:
        e = self._epoch[0]
        self._epoch[0] += 1
        return e

    def run(
        self,
        metric_name: str,
        question: str,
        fallback_sql: Optional[str] = None,
        filter_logic: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Full agent round-trip for one metric request.

        1. Check memory first (gate check on cached AMUs).
        2. If blocked/miss: execute SQL (via LLM or fallback_sql).
        3. sqlglot extracts lineage from executed SQL.
        4. Build AMU, write to memory, log conflict if any.

        Returns a result dict with all relevant fields for the experiment report.
        """
        t0 = time.perf_counter()

        # ── Step 1: Check memory for a safe cached AMU ─────────────────────
        check = self.memory.request(metric_name, self.department)
        # Note: We call request without a fresh AMU first to see the gate outcome.
        # If it hits a safe cached result, we're done (reused=True).
        # If blocked/miss, we need to run SQL. We undo the log entry by popping it.
        #
        # Actually, NorthwindLineageSystem.request with no fresh_amu just checks;
        # only writes fresh if fresh_amu is provided. So this is safe.
        #
        # Implementation note: request() without fresh_amu=None will:
        #   - If a safe candidate exists: return reused=True (no write)
        #   - If blocked/miss: return reused=False (no write yet)

        if check["reused"]:
            elapsed = (time.perf_counter() - t0) * 1000
            self._log(f"[REUSE] {metric_name} from {check['source_dept']}'s AMU "
                      f"(gate passed, hash={check['definition_hash'][:8]})")
            return {
                "scenario": metric_name,
                "department": self.department,
                "action": "reuse",
                "blocked": check["blocked"],
                "blocking_tags": check["blocking_tags"],
                "source_dept": check["source_dept"],
                "sql": None,
                "lineage_steps": [],
                "sensitivity_tags": [],
                "definition_hash": check["definition_hash"],
                "conflict": False,
                "elapsed_ms": round(elapsed, 3),
                "question": question,
                "answer": f"[Retrieved from {check['source_dept']} AMU in memory]",
            }

        # ── Step 2: Need fresh computation — run SQL ────────────────────────
        sql = None
        answer = None
        lineage_steps = []

        if self.llm_agent is not None:
            # LLM mode: Ollama generates the SQL
            self._log(f"[LLM] Asking Ollama: {question}")
            sql, answer, lineage_steps = self.llm_agent.query(question)
            if sql is None and fallback_sql:
                self._log("[LLM] No SQL captured from LLM output, using fallback SQL")
                sql = fallback_sql
                lineage_steps = extract_lineage_from_sql(sql)
        else:
            # Demo mode: use pre-defined SQL
            sql = fallback_sql
            if sql:
                lineage_steps = extract_lineage_from_sql(sql)

        if sql is None:
            self._log(f"[WARN] No SQL available for {metric_name} / {self.department}")
            return {
                "scenario": metric_name, "department": self.department,
                "action": "error", "error": "no SQL available",
                "elapsed_ms": 0, "question": question,
            }

        # ── Step 3: Execute SQL and get result value ────────────────────────
        try:
            result_text = self.executor.run_and_format(sql)
            rows, _ = self.executor.last_rows, self.executor.last_columns
            value = float(len(rows))  # use row count as scalar value
        except Exception as ex:
            self._log(f"[SQL ERROR] {ex}")
            result_text = f"(SQL error: {ex})"
            value = 0.0

        # ── Step 4: Build AMU from sqlglot-extracted lineage ───────────────
        fresh_amu, raw_steps = sql_to_amu(
            sql=sql,
            metric_name=metric_name,
            value=value,
            department=self.department,
            epoch=self._next_epoch(),
            filter_logic=filter_logic,
        )

        # ── Step 5: Attempt memory retrieval with fresh AMU as fallback ────
        #   (NorthwindLineageSystem.request will write fresh_amu if no safe cache)
        final_check = self.memory.request(
            metric_name, self.department,
            fresh_amu=fresh_amu, fresh_raw_steps=raw_steps,
        )

        elapsed = (time.perf_counter() - t0) * 1000
        action = "compute+write" if not final_check["reused"] else "reuse"
        self._log(
            f"[{action.upper()}] {metric_name} | tags={sorted(fresh_amu.sensitivity_tags)} "
            f"| hash={fresh_amu.definition_hash[:8]} "
            f"| conflict={final_check['conflict_flagged']} "
            f"| blocked_by={sorted(check['blocking_tags'])}"
        )

        return {
            "scenario": metric_name,
            "department": self.department,
            "action": action,
            "blocked": check["blocked"],
            "blocking_tags": sorted(check["blocking_tags"]),
            "source_dept": self.department,
            "sql": sql.strip(),
            "lineage_steps": raw_steps,
            "sensitivity_tags": sorted(fresh_amu.sensitivity_tags),
            "definition_hash": fresh_amu.definition_hash,
            "conflict": final_check["conflict_flagged"],
            "elapsed_ms": round(elapsed, 3),
            "question": question,
            "answer": answer or result_text,
            "result_preview": result_text[:500],
        }

    def _log(self, msg: str):
        if self.verbose:
            print(f"  [{self.department}] {msg}")
