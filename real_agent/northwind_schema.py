"""
northwind_schema.py
====================
Northwind-specific schema configuration for the real-agent experiment.

Defines:
  - NORTHWIND_SENSITIVE: columns in the sensitive registry S
  - NORTHWIND_PERMISSIONS: per-department permitted column sets P(d)
  - EXPERIMENT_QUERIES: realistic SQL queries used by each department agent
  - NORTHWIND_DEPT_QUESTIONS: natural-language questions (for LLM mode)

These definitions mirror the structure used in model.py for the synthetic
experiments but are grounded in the actual Northwind database schema.

Northwind table schema (SQLite version — jpwhite3/northwind-SQLite3):
  Customers(CustomerID, CompanyName, ContactName, ContactTitle, Address,
            City, Region, PostalCode, Country, Phone, Fax)
  Orders(OrderID, CustomerID, EmployeeID, OrderDate, RequiredDate, ShippedDate,
         ShipVia, Freight, ShipName, ShipAddress, ShipCity, ShipRegion,
         ShipPostalCode, ShipCountry)
  Order Details(OrderID, ProductID, UnitPrice, Quantity, Discount)
  Products(ProductID, ProductName, SupplierID, CategoryID, QuantityPerUnit,
           UnitPrice, UnitsInStock, UnitsOnOrder, ReorderLevel, Discontinued)
  Categories(CategoryID, CategoryName, Description, Picture)
  Employees(EmployeeID, LastName, FirstName, Title, TitleOfCourtesy, BirthDate,
            HireDate, Address, City, Region, PostalCode, Country, HomePhone,
            Extension, Photo, Notes, ReportsTo, PhotoPath)
  Suppliers(SupplierID, CompanyName, ContactName, ContactTitle, Address, City,
            Region, PostalCode, Country, Phone, Fax, HomePage)
  Shippers(ShipperID, CompanyName, Phone)
"""

# ---------------------------------------------------------------------------
# Sensitive registry S — columns that trigger the gate
# ---------------------------------------------------------------------------
# All column names stored normalized (lowercase, spaces → underscores)

NORTHWIND_SENSITIVE = {
    "unitprice",    # commercial pricing data — restricted from Operations
    "freight",      # shipping cost (financial) — restricted from Operations
    "homephone",    # employee personal contact — restricted from Sales/Operations
    "birthdate",    # employee personal data   — restricted from Sales/Operations
}

# ---------------------------------------------------------------------------
# Department permission sets P(d)
# ---------------------------------------------------------------------------

NORTHWIND_PERMISSIONS = {

    # Finance: full access — all business and PII columns
    "Finance": {
        # Order financial data
        "orderid", "customerid", "employeeid", "orderdate", "requireddate",
        "shippeddate", "shipvia", "freight",  # freight = sensitive, Finance allowed
        "shipname", "shipaddress", "shipcity", "shipregion",
        "shippostalcode", "shipcountry",
        # Order line items
        "productid", "unitprice", "quantity", "discount",  # unitprice = sensitive, Finance allowed
        # Products
        "productname", "supplierid", "categoryid", "quantityperunit",
        "unitsinstock", "unitsonorder", "reorderlevel", "discontinued",
        # Categories
        "categoryname", "description",
        # Customers
        "companyname", "contactname", "contacttitle",
        "address", "city", "region", "postalcode", "country", "phone", "fax",
        # Employees — including PII
        "lastname", "firstname", "title", "titleofcourtesy",
        "hiredate", "birthdate", "homephone",  # both PII cols, Finance allowed
        "extension", "notes", "reportsto",
        # Suppliers / Shippers
        "homepage",
        # Misc
        "shipperid", "picture",
    },

    # Sales: customer-facing + pricing data; NO employee PII
    "Sales": {
        "orderid", "customerid", "employeeid", "orderdate", "requireddate",
        "shippeddate", "shipvia", "shipname", "shipaddress", "shipcity",
        "shipregion", "shippostalcode", "shipcountry",
        "productid", "unitprice", "quantity", "discount",  # unitprice allowed for Sales
        "productname", "supplierid", "categoryid", "quantityperunit",
        "unitsinstock", "unitsonorder", "reorderlevel", "discontinued",
        "categoryname", "description",
        "companyname", "contactname", "contacttitle",
        "address", "city", "region", "postalcode", "country", "phone", "fax",
        # Employees — names/title OK but NOT homephone/birthdate
        "lastname", "firstname", "title", "hiredate",
        "homepage",
    },

    # Operations: logistics + inventory; NO pricing, NO employee PII
    "Operations": {
        "orderid", "customerid", "employeeid", "orderdate", "requireddate",
        "shippeddate", "shipvia", "shipname", "shipaddress", "shipcity",
        "shipregion", "shippostalcode", "shipcountry",
        # Order details: quantity & discount OK, but NOT unitprice
        "productid", "quantity", "discount",
        # Products: no unitprice
        "productname", "supplierid", "categoryid", "quantityperunit",
        "unitsinstock", "unitsonorder", "reorderlevel", "discontinued",
        "categoryname", "description",
        # Customers: public info only (no phone — PII consideration)
        "companyname", "contacttitle", "address", "city", "region",
        "postalcode", "country",
        # Employees: names only
        "lastname", "firstname", "title",
        "homepage",
    },

    # HR: employee-centric; full PII; limited business data
    "HR": {
        "employeeid", "lastname", "firstname", "title", "titleofcourtesy",
        "hiredate", "birthdate", "homephone",  # PII allowed for HR
        "address", "city", "region", "postalcode", "country", "extension",
        "notes", "reportsto",
        # Minimal order context for org charts
        "orderid", "orderdate", "customerid",
    },
}


# ---------------------------------------------------------------------------
# Pre-defined realistic SQL queries (used in demo mode without Ollama)
# ---------------------------------------------------------------------------
# Each entry: (metric_name, department, question, sql, notes)
# SQL uses actual Northwind column names (case-insensitive in SQLite)

EXPERIMENT_QUERIES = {

    # ── Scenario A: Revenue by product category ──────────────────────────
    # Uses UnitPrice → sensitive → gate blocks Operations
    "revenue_by_category_finance": {
        "metric_name": "revenue_by_category",
        "department": "Finance",
        "question": "What is the total revenue for each product category?",
        "sql": """
            SELECT c.CategoryName,
                   ROUND(SUM(od.UnitPrice * od.Quantity * (1.0 - od.Discount)), 2) AS TotalRevenue
            FROM   Categories c
            JOIN   Products p          ON c.CategoryID = p.CategoryID
            JOIN   "Order Details" od  ON p.ProductID  = od.ProductID
            GROUP  BY c.CategoryName
            ORDER  BY TotalRevenue DESC
        """,
        "note": "Uses UnitPrice (sensitive). Finance has permission. Writes AMU.",
    },

    "revenue_by_category_sales": {
        "metric_name": "revenue_by_category",
        "department": "Sales",
        "question": "What is the total revenue for each product category?",
        "sql": None,  # Will attempt cache lookup first (Sales has unitprice permission)
        "note": "Sales CAN see unitprice → gate passes → REUSE Finance AMU.",
    },

    "revenue_by_category_operations": {
        "metric_name": "revenue_by_category",
        "department": "Operations",
        "question": "What is the unit volume (quantity sold) by product category?",
        # Operations cannot use unitprice → reformulates as quantity-only metric
        "sql": """
            SELECT c.CategoryName,
                   SUM(od.Quantity) AS TotalUnitsSold
            FROM   Categories c
            JOIN   Products p          ON c.CategoryID = p.CategoryID
            JOIN   "Order Details" od  ON p.ProductID  = od.ProductID
            GROUP  BY c.CategoryName
            ORDER  BY TotalUnitsSold DESC
        """,
        "note": "Operations blocked from Finance AMU (unitprice). Fallback: quantity-only SQL. "
                "Conflict flagged: different definition_hash (volume vs revenue).",
    },

    # ── Scenario B: Employee directory ───────────────────────────────────
    # Uses HomePhone → sensitive → gate blocks Sales / Operations
    "employee_directory_hr": {
        "metric_name": "employee_directory",
        "department": "HR",
        "question": "What are the employees' names, titles, and contact phone numbers?",
        "sql": """
            SELECT e.FirstName, e.LastName, e.Title, e.HomePhone, e.City, e.Country
            FROM   Employees e
            ORDER  BY e.LastName
        """,
        "note": "Uses HomePhone (sensitive). HR has permission. Writes AMU.",
    },

    "employee_directory_finance": {
        "metric_name": "employee_directory",
        "department": "Finance",
        "question": "What are the employees' names, titles, and contact phone numbers?",
        "sql": None,  # Will attempt cache lookup (Finance has homephone permission)
        "note": "Finance CAN see homephone → gate passes → REUSE HR AMU.",
    },

    "employee_directory_sales": {
        "metric_name": "employee_directory",
        "department": "Sales",
        "question": "What are the employee names and titles (no personal contact info)?",
        "sql": """
            SELECT e.FirstName, e.LastName, e.Title, e.HireDate, e.City
            FROM   Employees e
            ORDER  BY e.LastName
        """,
        "note": "Sales blocked from HR AMU (homephone). Fallback: names/titles only. "
                "Conflict flagged: different definition_hash.",
    },

    # ── Scenario C: Safe metric — no sensitive columns ───────────────────
    "orders_by_country_finance": {
        "metric_name": "orders_by_country",
        "department": "Finance",
        "question": "How many orders were placed from each ship-to country?",
        "sql": """
            SELECT o.ShipCountry, COUNT(o.OrderID) AS OrderCount
            FROM   Orders o
            GROUP  BY o.ShipCountry
            ORDER  BY OrderCount DESC
        """,
        "note": "No sensitive columns. Writes AMU with sensitivity_tags = {}.",
    },

    "orders_by_country_operations": {
        "metric_name": "orders_by_country",
        "department": "Operations",
        "question": "How many orders were placed from each ship-to country?",
        "sql": None,  # Will attempt cache lookup
        "note": "No sensitive columns in AMU → gate passes → REUSE Finance AMU.",
    },

    "orders_by_country_sales": {
        "metric_name": "orders_by_country",
        "department": "Sales",
        "question": "How many orders were placed from each ship-to country?",
        "sql": None,  # Will attempt cache lookup
        "note": "No sensitive columns in AMU → gate passes → REUSE Finance AMU.",
    },
}

# ---------------------------------------------------------------------------
# Natural-language question prompts for LLM mode (Ollama)
# ---------------------------------------------------------------------------

NORTHWIND_DEPT_QUESTIONS = {
    "Finance": [
        "What is the total revenue for each product category?",
        "Which customers have placed the most orders?",
        "What is the average freight cost per ship country?",
    ],
    "Sales": [
        "What is the total revenue for each product category?",
        "Which products are selling the most units?",
        "How many orders did each customer place this year?",
    ],
    "Operations": [
        "How many units were sold per product category?",
        "What is the average shipping delay by shipper?",
        "How many orders were placed from each ship-to country?",
    ],
    "HR": [
        "What are the employee names, titles, and phone numbers?",
        "Which employees report to which manager?",
        "What is the distribution of employees by city?",
    ],
}
