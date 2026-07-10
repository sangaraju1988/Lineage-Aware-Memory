"""
create_northwind.py
===================
Creates a local Northwind-compatible SQLite database with realistic sample data.

Used as a fallback when the jpwhite3/northwind-SQLite3 download is unavailable.
Schema matches the canonical Northwind tables and column names exactly so that
the real_agent experiment SQL queries work without modification.

Tables: Categories, Suppliers, Customers, Employees, Shippers,
        Products, Orders, "Order Details"
"""

import sqlite3
import os
import random
from datetime import date, timedelta

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "northwind.db"
)

DDL = """
CREATE TABLE IF NOT EXISTS Categories (
    CategoryID    INTEGER PRIMARY KEY,
    CategoryName  TEXT    NOT NULL,
    Description   TEXT,
    Picture       BLOB
);

CREATE TABLE IF NOT EXISTS Suppliers (
    SupplierID    INTEGER PRIMARY KEY,
    CompanyName   TEXT    NOT NULL,
    ContactName   TEXT,
    ContactTitle  TEXT,
    Address       TEXT,
    City          TEXT,
    Region        TEXT,
    PostalCode    TEXT,
    Country       TEXT,
    Phone         TEXT,
    Fax           TEXT,
    HomePage      TEXT
);

CREATE TABLE IF NOT EXISTS Customers (
    CustomerID    TEXT    PRIMARY KEY,
    CompanyName   TEXT    NOT NULL,
    ContactName   TEXT,
    ContactTitle  TEXT,
    Address       TEXT,
    City          TEXT,
    Region        TEXT,
    PostalCode    TEXT,
    Country       TEXT,
    Phone         TEXT,
    Fax           TEXT
);

CREATE TABLE IF NOT EXISTS Employees (
    EmployeeID    INTEGER PRIMARY KEY,
    LastName      TEXT    NOT NULL,
    FirstName     TEXT    NOT NULL,
    Title         TEXT,
    TitleOfCourtesy TEXT,
    BirthDate     TEXT,
    HireDate      TEXT,
    Address       TEXT,
    City          TEXT,
    Region        TEXT,
    PostalCode    TEXT,
    Country       TEXT,
    HomePhone     TEXT,
    Extension     TEXT,
    Photo         BLOB,
    Notes         TEXT,
    ReportsTo     INTEGER,
    PhotoPath     TEXT
);

CREATE TABLE IF NOT EXISTS Shippers (
    ShipperID     INTEGER PRIMARY KEY,
    CompanyName   TEXT    NOT NULL,
    Phone         TEXT
);

CREATE TABLE IF NOT EXISTS Products (
    ProductID         INTEGER PRIMARY KEY,
    ProductName       TEXT    NOT NULL,
    SupplierID        INTEGER,
    CategoryID        INTEGER,
    QuantityPerUnit   TEXT,
    UnitPrice         REAL    DEFAULT 0,
    UnitsInStock      INTEGER DEFAULT 0,
    UnitsOnOrder      INTEGER DEFAULT 0,
    ReorderLevel      INTEGER DEFAULT 0,
    Discontinued      INTEGER DEFAULT 0,
    FOREIGN KEY (SupplierID) REFERENCES Suppliers(SupplierID),
    FOREIGN KEY (CategoryID) REFERENCES Categories(CategoryID)
);

CREATE TABLE IF NOT EXISTS Orders (
    OrderID        INTEGER PRIMARY KEY,
    CustomerID     TEXT,
    EmployeeID     INTEGER,
    OrderDate      TEXT,
    RequiredDate   TEXT,
    ShippedDate    TEXT,
    ShipVia        INTEGER,
    Freight        REAL    DEFAULT 0,
    ShipName       TEXT,
    ShipAddress    TEXT,
    ShipCity       TEXT,
    ShipRegion     TEXT,
    ShipPostalCode TEXT,
    ShipCountry    TEXT,
    FOREIGN KEY (CustomerID)  REFERENCES Customers(CustomerID),
    FOREIGN KEY (EmployeeID)  REFERENCES Employees(EmployeeID),
    FOREIGN KEY (ShipVia)     REFERENCES Shippers(ShipperID)
);

CREATE TABLE IF NOT EXISTS "Order Details" (
    OrderID    INTEGER NOT NULL,
    ProductID  INTEGER NOT NULL,
    UnitPrice  REAL    NOT NULL DEFAULT 0,
    Quantity   INTEGER NOT NULL DEFAULT 1,
    Discount   REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (OrderID, ProductID),
    FOREIGN KEY (OrderID)   REFERENCES Orders(OrderID),
    FOREIGN KEY (ProductID) REFERENCES Products(ProductID)
);
"""

CATEGORIES = [
    (1, "Beverages",    "Soft drinks, coffees, teas, beers, and ales"),
    (2, "Condiments",   "Sweet and savory sauces, relishes, spreads, and seasonings"),
    (3, "Confections",  "Desserts, candies, and sweet breads"),
    (4, "Dairy Products","Cheeses"),
    (5, "Grains/Cereals","Breads, crackers, pasta, and cereal"),
    (6, "Meat/Poultry", "Prepared meats"),
    (7, "Produce",      "Dried fruit and bean curd"),
    (8, "Seafood",      "Seaweed and fish"),
]

SUPPLIERS = [
    (1,  "Exotic Liquids",          "Charlotte Cooper",  "Purchasing Manager",  "49 Gilbert St.",     "London",     None,   "EC1 4SD",  "UK",        "(171) 555-2222",  None,         None),
    (2,  "New Orleans Cajun Delights","Shelley Burke",   "Order Administrator", "P.O. Box 78934",     "New Orleans","LA",   "70117",    "USA",       "(100) 555-4822",  None,         "#CAJUN.HTM#"),
    (3,  "Grandma Kelly's Homestead","Regina Murphy",   "Sales Representative","707 Oxford Rd.",     "Ann Arbor",  "MI",   "48104",    "USA",       "(313) 555-5735",  "(313) 555-3349",None),
    (4,  "Tokyo Traders",            "Yoshi Nagase",    "Marketing Manager",   "9-8 Sekimai",        "Tokyo",      None,   "100",      "Japan",     "(03) 3555-5011",  None,         None),
    (5,  "Cooperativa de Quesos",    "Antonio del Valle","Export Administrator","Calle del Rosal 4",  "Oviedo",     "Asturias","33007","Spain",    "(98) 598 76 54",  None,         None),
    (6,  "Mayumi's",                 "Mayumi Ohna",     "Marketing Representative","92 Setsuko",     "Osaka",      None,   "545",      "Japan",     "(06) 431-7877",   None,         "Mayumi's (on the World Wide Web)#http://www.microsoft.com/accessdev/sampleapps/mayumi.htm#"),
    (7,  "Pavlova, Ltd.",            "Ian Devling",     "Marketing Manager",   "74 Rose St.",        "Melbourne",  "Victoria","3058", "Australia", "(03) 444-2343",  "(03) 444-6588",None),
    (8,  "Specialty Biscuits, Ltd.", "Peter Wilson",    "Sales Representative","29 King's Way",      "Manchester", None,   "M14 GSD",  "UK",        "(161) 555-4448",  None,         None),
    (9,  "PB Knäckebröd AB",         "Lars Peterson",   "Sales Agent",         "Kaloadagatan 13",    "Göteborg",   None,   "S-345 67", "Sweden",    "031-987 65 43",   "031-987 65 91",None),
    (10, "Refrescos Americanas LTDA","Carlos Diaz",     "Marketing Manager",   "Av. das Americanas 12.890","Sao Paulo",None,"5442",  "Brazil",    "(11) 555 4640",   None,         None),
]

CUSTOMERS = [
    ("ALFKI","Alfreds Futterkiste",       "Maria Anders",  "Sales Representative","Obere Str. 57",   "Berlin",  None,       "12209","Germany",  "030-0074321",  "030-0076545"),
    ("ANATR","Ana Trujillo Emparedados",   "Ana Trujillo",  "Owner",              "Avda. de la Constitución 2222","México D.F.",None,"05021","Mexico","(5) 555-4729","(5) 555-3745"),
    ("ANTON","Antonio Moreno Taquería",   "Antonio Moreno","Owner",              "Mataderos  2312", "México D.F.",None,    "05023","Mexico",  "(5) 555-3932",  None),
    ("AROUT","Around the Horn",           "Thomas Hardy",  "Sales Representative","120 Hanover Sq.", "London",  None,       "WA1 1DP","UK",    "(171) 555-7788","(171) 555-6750"),
    ("BERGS","Berglunds snabbköp",        "Christina Berglund","Order Administrator","Berguvsvägen  8","Luleå",None,"S-958 22","Sweden","0921-12 34 65","0921-12 34 67"),
    ("BLAUS","Blauer See Delikatessen",   "Hanna Moos",    "Sales Representative","Forsterstr. 57",  "Mannheim",None,       "68306","Germany",  "0621-08460",   "0621-08924"),
    ("BLONP","Blondel père et fils",      "Frédérique Citeaux","Marketing Manager","24, place Kléber","Strasbourg",None,   "67000","France",   "88.60.15.31",  "88.60.15.32"),
    ("BOLID","Bólido Comidas preparadas", "Martín Sommer", "Owner",              "C/ Araquil, 67",  "Madrid",  None,       "28023","Spain",    "(91) 555 22 82","(91) 555 91 99"),
    ("BONAP","Bon app'",                  "Laurence Lebihan","Owner",            "12, rue des Bouchers","Marseille",None,  "13008","France",   "91.24.45.40",  "91.24.45.41"),
    ("BOTTM","Bottom-Dollar Marketse",    "Elizabeth Lincoln","Accounting Manager","23 Tsawassen Blvd.","Tsawassen","BC","T2F 8M4","Canada","(604) 555-4729","(604) 555-3745"),
    ("BSBEV","B's Beverages",            "Victoria Ashworth","Sales Representative","Fauntleroy Circus","London",None,"EC2 5NT","UK","(171) 555-1212",None),
    ("CACTU","Cactus Comidas para llevar","Patricio Simpson","Sales Agent",      "Cerrito 333",     "Buenos Aires",None,"1010","Argentina","(1) 135-5555","(1) 135-4892"),
    ("CENTC","Centro comercial Moctezuma","Francisco Chang","Marketing Manager",  "Sierras de Granada 9993","México D.F.",None,"05022","Mexico","(5) 555-3392","(5) 555-7293"),
    ("CHOPS","Chop-suey Chinese",         "Yang Wang",     "Owner",              "Hauptstr. 29",    "Bern",    None,       "3012", "Switzerland","0452-076545",None),
    ("COMMI","Comércio Mineiro",          "Pedro Afonso",  "Sales Associate",    "Av. dos Lusíadas, 23","Sao Paulo",None,"05432-043","Brazil","(11) 555-7647",None),
    ("CONSH","Consolidated Holdings",     "Elizabeth Brown","Sales Representative","Berkeley Gardens 12  Brewery","London",None,"WX1 6LT","UK","(171) 555-2282","(171) 555-9199"),
    ("DRACD","Drachenblut Delikatessen",  "Sven Ottlieb",  "Order Administrator","Walserweg 21",    "Aachen",  None,       "52066","Germany",  "0241-039123",  "0241-059428"),
    ("DUMON","Du monde entier",           "Janine Labrune","Owner",              "67, rue des Cinquante Otages","Nantes",None,"44000","France","40.67.88.88","40.67.89.89"),
    ("EASTC","Eastern Connection",        "Ann Devon",     "Sales Agent",        "35 King George",  "London",  None,       "WX3 6FW","UK",    "(171) 555-0297","(171) 555-3373"),
    ("ERNSH","Ernst Handel",              "Roland Mendel", "Sales Manager",      "Kirchgasse 6",    "Graz",    None,       "8010", "Austria",  "7675-3425",    "7675-3426"),
]

EMPLOYEES = [
    (1,"Davolio",  "Nancy",   "Sales Representative",     "Ms.", "1968-12-08","1992-05-01","507 - 20th Ave. E.","Seattle","WA","98122","USA","(206) 555-9857","5467",None,"Education includes a BA in psychology from Colorado State University in 1970.  She also completed The Art of the Cold Call.",2,None),
    (2,"Fuller",   "Andrew",  "Vice President, Sales",    "Dr.", "1952-02-19","1992-08-14","908 W. Capital Way","Tacoma","WA","98401","USA","(206) 555-9482","3457",None,"Andrew received his BTS commercial in 1974 and a Ph.D. in international marketing from the University of Dallas in 1981.",None,None),
    (3,"Leverling","Janet",   "Sales Representative",     "Ms.", "1963-08-30","1992-04-01","722 Moss Bay Blvd.","Kirkland","WA","98033","USA","(206) 555-3412","3355",None,"Janet has a BS degree in chemistry from Boston College (1984).",2,None),
    (4,"Peacock",  "Margaret","Sales Representative",     "Mrs.","1937-09-19","1993-05-03","4110 Old Redmond Rd.","Redmond","WA","98052","USA","(206) 555-8122","5176",None,"Margaret holds a BA in English literature from Concordia College (1958) and an MA from the American Institute of Culinary Arts (1966).",2,None),
    (5,"Buchanan", "Steven",  "Sales Manager",            "Mr.", "1955-03-04","1993-10-17","14 Garrett Hill","London",None,"SW1 8JR","UK","(71) 555-4848","3453",None,"Steven Buchanan graduated from St. Andrews University, Scotland, with a BSC degree in 1976.",2,None),
    (6,"Suyama",   "Michael", "Sales Representative",     "Mr.", "1963-07-02","1993-10-17","Coventry House Miner Rd.","London",None,"EC2 7JR","UK","(71) 555-7773","428",None,"Michael is a graduate of Sussex University (MA, economics, 1983) and the University of California at Los Angeles (MBA, marketing, 1986).",5,None),
    (7,"King",     "Robert",  "Sales Representative",     "Mr.", "1960-05-29","1994-01-02","Edgeham Hollow Winchester Way","London",None,"RG1 9SP","UK","(71) 555-5598","465",None,"Robert King served in the Peace Corps and traveled extensively before completing his degree.",5,None),
    (8,"Callahan", "Laura",   "Inside Sales Coordinator","Ms.", "1958-01-09","1994-03-05","4726 - 11th Ave. N.E.","Seattle","WA","98105","USA","(206) 555-1189","2344",None,"Laura received a BA in psychology from the University of Washington.",2,None),
    (9,"Dodsworth","Anne",    "Sales Representative",     "Ms.", "1966-01-27","1994-11-15","7 Houndstooth Rd.","London",None,"WG2 7LT","UK","(71) 555-4444","452",None,"Anne has a BA degree in English from St. Lawrence College.",5,None),
]

SHIPPERS = [
    (1, "Speedy Express",  "(503) 555-9831"),
    (2, "United Package",  "(503) 555-3199"),
    (3, "Federal Shipping","(503) 555-9931"),
]

PRODUCTS = [
    (1,  "Chai",                          1, 1, "10 boxes x 20 bags",  18.00, 39, 0,  10, 0),
    (2,  "Chang",                         1, 1, "24 - 12 oz bottles",  19.00, 17, 40, 25, 0),
    (3,  "Aniseed Syrup",                 1, 2, "12 - 550 ml bottles",  10.00, 13, 70, 25, 0),
    (4,  "Chef Anton's Cajun Seasoning",  2, 2, "48 - 6 oz jars",      22.00, 53, 0,  0,  0),
    (5,  "Chef Anton's Gumbo Mix",        2, 2, "36 boxes",            21.35, 0,  0,  0,  1),
    (6,  "Grandma's Boysenberry Spread",  3, 2, "12 - 8 oz jars",      25.00, 120,0,  25, 0),
    (7,  "Uncle Bob's Organic Dried Pears",3,7, "12 - 1 lb pkgs.",     30.00, 15, 0,  10, 0),
    (8,  "Northwoods Cranberry Sauce",    3, 2, "12 - 12 oz jars",     40.00, 6,  0,  0,  0),
    (9,  "Mishi Kobe Niku",               4, 6, "18 - 500 g pkgs.",    97.00, 29, 0,  0,  1),
    (10, "Ikura",                         4, 8, "12 - 200 ml jars",    31.00, 31, 0,  0,  0),
    (11, "Queso Cabrales",                5, 4, "1 kg pkg.",           21.00, 22, 30, 30, 0),
    (12, "Queso Manchego La Pastora",     5, 4, "10 - 500 g pkgs.",    38.00, 86, 0,  0,  0),
    (13, "Konbu",                         6, 8, "2 kg box",             6.00, 24, 0,  5,  0),
    (14, "Tofu",                          6, 7, "40 - 100 g pkgs.",    23.25, 35, 0,  0,  0),
    (15, "Genen Shouyu",                  6, 2, "24 - 250 ml bottles", 15.50, 39, 0,  5,  0),
    (16, "Pavlova",                       7, 3, "32 - 500 g boxes",    17.45, 29, 0,  10, 0),
    (17, "Alice Mutton",                  7, 6, "20 - 1 kg tins",      39.00, 0,  0,  0,  1),
    (18, "Carnarvon Tigers",              7, 8, "16 kg pkg.",          62.50, 42, 0,  0,  0),
    (19, "Teatime Chocolate Biscuits",    8, 3, "10 boxes x 12 pieces",9.20, 25, 0,  5,  0),
    (20, "Sir Rodney's Marmalade",        8, 3, "30 gift boxes",       81.00, 40, 0,  0,  0),
    (21, "Sir Rodney's Scones",           8, 3, "24 pkgs. x 4 pieces", 10.00, 3,  40, 5,  0),
    (22, "Gustaf's Knäckebröd",           9, 5, "24 - 500 g pkgs.",    21.00, 104,0,  25, 0),
    (23, "Tunnbröd",                      9, 5, "12 - 250 g pkgs.",     9.00, 61, 0,  25, 0),
    (24, "Guaraná Fantástica",            10,1, "12 - 355 ml cans",     4.50, 20, 0,  0,  1),
    (25, "NuNuCa Nuß-Nougat-Creme",       2, 3, "20 - 450 g glasses",  14.00, 76, 0,  30, 0),
    (26, "Gumbär Gummibärchen",           2, 3, "100 - 250 g bags",    31.23, 15, 0,  0,  0),
    (27, "Schoggi Schokolade",            2, 3, "100 - 100 g pieces",  43.90, 49, 0,  30, 0),
    (28, "Rössle Sauerkraut",             2, 7, "25 - 825 g cans",     45.60, 26, 0,  0,  1),
    (29, "Thüringer Rostbratwurst",       2, 6, "50 bags x 30 sausgs.",123.79,0,  0,  0,  1),
    (30, "Nord-Ost Matjeshering",         3, 8, "10 - 200 g glasses",  25.89, 10, 0,  15, 0),
]

def generate_orders_and_details(customers, products, employees, shippers):
    """Generate realistic Northwind-style orders and order details."""
    random.seed(42)
    orders = []
    order_details = []

    customer_ids = [c[0] for c in customers]
    product_list = [(p[0], p[6]) for p in products]  # (ProductID, UnitPrice)
    employee_ids = [e[0] for e in employees]
    shipper_ids  = [s[0] for s in shippers]

    ship_countries = ["Germany", "UK", "USA", "France", "Spain", "Canada",
                      "Brazil", "Mexico", "Austria", "Sweden", "Switzerland"]
    ship_cities    = ["Berlin", "London", "New York", "Paris", "Madrid",
                      "Toronto", "São Paulo", "México", "Wien", "Göteborg", "Bern"]

    base_date = date(2024, 1, 1)
    order_id  = 10248  # Northwind orders start at 10248

    for i in range(200):  # 200 orders
        cust_id    = random.choice(customer_ids)
        emp_id     = random.choice(employee_ids)
        order_date = base_date + timedelta(days=random.randint(0, 540))
        req_date   = order_date + timedelta(days=random.randint(7, 21))
        ship_date  = order_date + timedelta(days=random.randint(1, 14))
        ship_via   = random.choice(shipper_ids)
        freight    = round(random.uniform(2.0, 200.0), 2)
        idx        = random.randint(0, len(ship_countries)-1)

        orders.append((
            order_id, cust_id, emp_id,
            order_date.isoformat(), req_date.isoformat(), ship_date.isoformat(),
            ship_via, freight,
            f"Ship {i}", f"Addr {i}", ship_cities[idx % len(ship_cities)],
            None, f"{10000 + i}", ship_countries[idx],
        ))

        # 1-5 line items per order
        n_lines = random.randint(1, 5)
        picked  = random.sample(product_list, min(n_lines, len(product_list)))
        for prod_id, list_price in picked:
            unit_price = round(list_price * random.uniform(0.9, 1.1), 2)
            quantity   = random.randint(1, 50)
            discount   = random.choice([0.0, 0.05, 0.10, 0.15, 0.20, 0.25])
            order_details.append((order_id, prod_id, unit_price, quantity, discount))

        order_id += 1

    return orders, order_details


def create_northwind_local(db_path: str = DEFAULT_DB_PATH, force: bool = False) -> str:
    """Create a local Northwind-compatible SQLite database from embedded data."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if os.path.exists(db_path) and not force:
        print(f"[create_northwind] DB already exists: {db_path}")
        return db_path

    print(f"[create_northwind] Building Northwind-compatible SQLite DB...")

    orders, order_details = generate_orders_and_details(
        CUSTOMERS, PRODUCTS, EMPLOYEES, SHIPPERS
    )

    conn = sqlite3.connect(db_path)
    conn.executescript(DDL)

    conn.executemany("INSERT OR IGNORE INTO Categories VALUES (?,?,?,?)",
                     [(r[0], r[1], r[2], None) for r in CATEGORIES])
    conn.executemany("INSERT OR IGNORE INTO Suppliers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", SUPPLIERS)
    conn.executemany("INSERT OR IGNORE INTO Customers VALUES (?,?,?,?,?,?,?,?,?,?,?)", CUSTOMERS)
    conn.executemany("INSERT OR IGNORE INTO Employees VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", EMPLOYEES)
    conn.executemany("INSERT OR IGNORE INTO Shippers VALUES (?,?,?)", SHIPPERS)
    conn.executemany("INSERT OR IGNORE INTO Products VALUES (?,?,?,?,?,?,?,?,?,?)", PRODUCTS)
    conn.executemany("INSERT OR IGNORE INTO Orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", orders)
    conn.executemany('INSERT OR IGNORE INTO "Order Details" VALUES (?,?,?,?,?)', order_details)
    conn.commit()
    conn.close()

    # Verify
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM "Order Details"')
    n_od = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) FROM Orders')
    n_o  = cur.fetchone()[0]
    conn.close()

    print(f"[create_northwind] Created: {n_o} orders, {n_od} order details → {db_path}")
    return db_path


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    path  = create_northwind_local(force=force)
    print(f"Done: {path}")
