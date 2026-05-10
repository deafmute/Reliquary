"""Create and locate bundled sample databases."""

from pathlib import Path
import sqlite3

SAMPLES_DIR = Path.home() / '.local' / 'share' / 'reliquary' / 'samples'

SAMPLES = {
    'music_store': {
        'name': 'Music Store',
        'filename': 'music_store.db',
        'description': 'Artists, albums, tracks, genres, customers and invoices',
        'icon': 'audio-x-generic-symbolic',
        'builder': '_build_music_store',
    },
    'northwind': {
        'name': 'Northwind Traders',
        'filename': 'northwind.db',
        'description': 'Products, orders, customers, employees and suppliers',
        'icon': 'x-office-spreadsheet-symbolic',
        'builder': '_build_northwind',
    },
}


def ensure_samples() -> dict[str, Path]:
    """Return {key: path} for all sample databases, creating them if needed."""
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    for key, meta in SAMPLES.items():
        path = SAMPLES_DIR / meta['filename']
        if not path.exists():
            globals()[meta['builder']](path)
        result[key] = path
    return result


def get_sample_path(key: str) -> Path:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    meta = SAMPLES[key]
    path = SAMPLES_DIR / meta['filename']
    if not path.exists():
        globals()[meta['builder']](path)
    return path


# ── Music Store ───────────────────────────────────────────────────────────

def _build_music_store(path: Path):
    conn = sqlite3.connect(path)
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE genres (
        genre_id   INTEGER PRIMARY KEY,
        name       TEXT NOT NULL
    );
    CREATE TABLE artists (
        artist_id  INTEGER PRIMARY KEY,
        name       TEXT NOT NULL
    );
    CREATE TABLE albums (
        album_id   INTEGER PRIMARY KEY,
        title      TEXT NOT NULL,
        artist_id  INTEGER NOT NULL REFERENCES artists(artist_id),
        year       INTEGER,
        genre_id   INTEGER REFERENCES genres(genre_id)
    );
    CREATE TABLE tracks (
        track_id    INTEGER PRIMARY KEY,
        title       TEXT NOT NULL,
        album_id    INTEGER NOT NULL REFERENCES albums(album_id),
        duration_ms INTEGER,
        track_no    INTEGER,
        price       REAL DEFAULT 0.99
    );
    CREATE TABLE customers (
        customer_id  INTEGER PRIMARY KEY,
        first_name   TEXT NOT NULL,
        last_name    TEXT NOT NULL,
        email        TEXT UNIQUE NOT NULL,
        country      TEXT,
        city         TEXT
    );
    CREATE TABLE invoices (
        invoice_id   INTEGER PRIMARY KEY,
        customer_id  INTEGER NOT NULL REFERENCES customers(customer_id),
        invoice_date TEXT NOT NULL,
        total        REAL NOT NULL
    );
    CREATE TABLE invoice_items (
        item_id     INTEGER PRIMARY KEY,
        invoice_id  INTEGER NOT NULL REFERENCES invoices(invoice_id),
        track_id    INTEGER NOT NULL REFERENCES tracks(track_id),
        quantity    INTEGER NOT NULL DEFAULT 1,
        unit_price  REAL NOT NULL
    );
    CREATE TABLE playlists (
        playlist_id INTEGER PRIMARY KEY,
        name        TEXT NOT NULL
    );
    CREATE TABLE playlist_tracks (
        playlist_id INTEGER NOT NULL REFERENCES playlists(playlist_id),
        track_id    INTEGER NOT NULL REFERENCES tracks(track_id),
        PRIMARY KEY (playlist_id, track_id)
    );
    """)

    genres = [
        (1, 'Rock'), (2, 'Jazz'), (3, 'Classical'), (4, 'Blues'),
        (5, 'Electronic'), (6, 'Hip-Hop'), (7, 'Metal'), (8, 'Pop'),
        (9, 'Country'), (10, 'Folk'),
    ]
    c.executemany('INSERT INTO genres VALUES (?,?)', genres)

    artists = [
        (1, 'Miles Davis'), (2, 'Pink Floyd'), (3, 'The Beatles'),
        (4, 'Led Zeppelin'), (5, 'Beethoven'), (6, 'Johnny Cash'),
        (7, 'Radiohead'), (8, 'David Bowie'), (9, 'Kendrick Lamar'),
        (10, 'Daft Punk'), (11, 'Massive Attack'), (12, 'Arctic Monkeys'),
        (13, 'Bob Dylan'), (14, 'Nina Simone'), (15, 'Coltrane'),
    ]
    c.executemany('INSERT INTO artists VALUES (?,?)', artists)

    albums = [
        (1,  'Kind of Blue',          1, 1959, 2),
        (2,  'The Dark Side of the Moon', 2, 1973, 1),
        (3,  'Abbey Road',            3, 1969, 1),
        (4,  'Led Zeppelin IV',       4, 1971, 1),
        (5,  'Symphony No. 9',        5, 1824, 3),
        (6,  'At Folsom Prison',      6, 1968, 9),
        (7,  'OK Computer',           7, 1997, 1),
        (8,  'The Rise and Fall of Ziggy Stardust', 8, 1972, 1),
        (9,  'To Pimp a Butterfly',   9, 2015, 6),
        (10, 'Random Access Memories', 10, 2013, 5),
        (11, 'Mezzanine',             11, 1998, 5),
        (12, 'AM',                    12, 2013, 1),
        (13, 'Highway 61 Revisited',  13, 1965, 10),
        (14, 'I Put a Spell on You',  14, 1965, 4),
        (15, 'A Love Supreme',        15, 1965, 2),
    ]
    c.executemany('INSERT INTO albums VALUES (?,?,?,?,?)', albums)

    tracks_data = []
    track_names = {
        1: ['So What', 'Freddie Freeloader', 'Blue in Green', 'All Blues', 'Flamenco Sketches'],
        2: ['Speak to Me', 'Breathe', 'On the Run', 'Time', 'The Great Gig in the Sky',
            'Money', 'Us and Them', 'Any Colour You Like', 'Brain Damage', 'Eclipse'],
        3: ['Come Together', 'Something', 'Maxwell\'s Silver Hammer', 'Oh! Darling',
            'Octopus\'s Garden', 'I Want You', 'Here Comes the Sun', 'Because',
            'You Never Give Me Your Money', 'Golden Slumbers'],
        4: ['Black Dog', 'Rock and Roll', 'The Battle of Evermore', 'Stairway to Heaven',
            'Misty Mountain Hop', 'Four Sticks', 'Going to California', 'When the Levee Breaks'],
        5: ['I. Allegro', 'II. Adagio', 'III. Scherzo', 'IV. Presto'],
        6: ['Folsom Prison Blues', 'Dark as the Dungeon', "I Still Miss Someone", 'Cocaine Blues',
            '25 Minutes to Go', 'Orange Blossom Special'],
        7: ['Airbag', 'Paranoid Android', 'Subterranean Homesick Alien', 'Exit Music',
            'Let Down', 'Karma Police', 'Fitter Happier', 'Electioneering',
            'Climbing Up the Walls', 'No Surprises', 'Lucky', 'The Tourist'],
        8: ['Five Years', 'Soul Love', 'Moonage Daydream', 'Starman',
            'It Ain\'t Easy', 'Lady Stardust', 'Star', 'Hang On to Yourself',
            'Ziggy Stardust', 'Suffragette City', 'Rock \'n\' Roll Suicide'],
        9: ['Wesley\'s Theory', 'For Free?', 'King Kunta', 'Institutionalized',
            'These Walls', 'u', 'Alright', 'For Sale?', 'Momma', 'Hood Politics',
            'How Much a Dollar Cost', 'Complexion', 'The Blacker the Berry'],
        10: ['Give Life Back to Music', 'The Game of Love', 'Giorgio by Moroder',
             'Within', 'Instant Crush', 'Lose Yourself to Dance', 'Touch',
             'Get Lucky', 'Beyond', 'Motherboard', 'Fragments of Time', 'Doin\' it Right'],
    }

    tid = 1
    for album_id, names in track_names.items():
        for i, name in enumerate(names, 1):
            tracks_data.append((tid, name, album_id, (180 + i * 13) * 1000, i, 0.99))
            tid += 1
    c.executemany('INSERT INTO tracks VALUES (?,?,?,?,?,?)', tracks_data)

    customers = [
        (1,  'Alice',   'Johnson', 'alice@example.com',   'USA',     'New York'),
        (2,  'Bob',     'Smith',   'bob@example.com',     'UK',      'London'),
        (3,  'Clara',   'Müller',  'clara@example.de',    'Germany', 'Berlin'),
        (4,  'Dmitri',  'Volkov',  'dmitri@example.ru',   'Russia',  'Moscow'),
        (5,  'Elena',   'Garcia',  'elena@example.es',    'Spain',   'Madrid'),
        (6,  'Fiona',   'Brown',   'fiona@example.au',    'Australia','Sydney'),
        (7,  'Georges', 'Dupont',  'georges@example.fr',  'France',  'Paris'),
        (8,  'Hana',    'Tanaka',  'hana@example.jp',     'Japan',   'Tokyo'),
        (9,  'Ivan',    'Novak',   'ivan@example.cz',     'Czech Republic', 'Prague'),
        (10, 'Julia',   'Rossi',   'julia@example.it',    'Italy',   'Rome'),
    ]
    c.executemany('INSERT INTO customers VALUES (?,?,?,?,?,?)', customers)

    invoices = [
        (1,  1, '2024-01-05', 9.90),
        (2,  2, '2024-01-12', 4.95),
        (3,  3, '2024-02-03', 12.87),
        (4,  4, '2024-02-14', 2.97),
        (5,  5, '2024-03-01', 7.92),
        (6,  6, '2024-03-18', 14.85),
        (7,  7, '2024-04-07', 5.94),
        (8,  8, '2024-04-22', 9.90),
        (9,  9, '2024-05-10', 3.96),
        (10, 10, '2024-05-30', 11.88),
        (11, 1, '2024-06-15', 6.93),
        (12, 3, '2024-07-04', 8.91),
    ]
    c.executemany('INSERT INTO invoices VALUES (?,?,?,?)', invoices)

    items = [
        (1,  1, 1,  1, 0.99), (2,  1, 2,  1, 0.99), (3,  1, 3,  1, 0.99),
        (4,  1, 4,  1, 0.99), (5,  1, 5,  1, 0.99), (6,  1, 6,  1, 0.99),
        (7,  1, 7,  1, 0.99), (8,  1, 8,  1, 0.99), (9,  1, 9,  1, 0.99),
        (10, 1, 10, 1, 0.99), (11, 2, 11, 1, 0.99), (12, 2, 12, 1, 0.99),
        (13, 2, 13, 1, 0.99), (14, 2, 14, 1, 0.99), (15, 2, 15, 1, 0.99),
    ]
    c.executemany('INSERT INTO invoice_items VALUES (?,?,?,?,?)', items)

    playlists = [(1, 'Jazz Essentials'), (2, 'Rock Classics'), (3, 'Late Night Chill')]
    c.executemany('INSERT INTO playlists VALUES (?,?)', playlists)

    pl_tracks = [(1,1),(1,2),(1,3),(1,4),(1,5),(2,11),(2,12),(2,13),(2,14),(3,21),(3,22)]
    c.executemany('INSERT INTO playlist_tracks VALUES (?,?)', pl_tracks)

    conn.commit()
    conn.close()


# ── Northwind-style traders ───────────────────────────────────────────────

def _build_northwind(path: Path):
    conn = sqlite3.connect(path)
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE categories (
        category_id   INTEGER PRIMARY KEY,
        name          TEXT NOT NULL,
        description   TEXT
    );
    CREATE TABLE suppliers (
        supplier_id   INTEGER PRIMARY KEY,
        company_name  TEXT NOT NULL,
        contact_name  TEXT,
        country       TEXT,
        city          TEXT,
        phone         TEXT
    );
    CREATE TABLE products (
        product_id    INTEGER PRIMARY KEY,
        name          TEXT NOT NULL,
        category_id   INTEGER REFERENCES categories(category_id),
        supplier_id   INTEGER REFERENCES suppliers(supplier_id),
        unit_price    REAL NOT NULL,
        units_in_stock INTEGER DEFAULT 0,
        discontinued  INTEGER DEFAULT 0
    );
    CREATE TABLE customers (
        customer_id   TEXT PRIMARY KEY,
        company_name  TEXT NOT NULL,
        contact_name  TEXT,
        country       TEXT,
        city          TEXT,
        phone         TEXT
    );
    CREATE TABLE employees (
        employee_id   INTEGER PRIMARY KEY,
        first_name    TEXT NOT NULL,
        last_name     TEXT NOT NULL,
        title         TEXT,
        hire_date     TEXT,
        country       TEXT,
        city          TEXT,
        reports_to    INTEGER REFERENCES employees(employee_id)
    );
    CREATE TABLE shippers (
        shipper_id    INTEGER PRIMARY KEY,
        company_name  TEXT NOT NULL,
        phone         TEXT
    );
    CREATE TABLE orders (
        order_id      INTEGER PRIMARY KEY,
        customer_id   TEXT REFERENCES customers(customer_id),
        employee_id   INTEGER REFERENCES employees(employee_id),
        order_date    TEXT NOT NULL,
        shipped_date  TEXT,
        shipper_id    INTEGER REFERENCES shippers(shipper_id),
        freight       REAL DEFAULT 0,
        ship_country  TEXT
    );
    CREATE TABLE order_details (
        order_id      INTEGER NOT NULL REFERENCES orders(order_id),
        product_id    INTEGER NOT NULL REFERENCES products(product_id),
        unit_price    REAL NOT NULL,
        quantity      INTEGER NOT NULL DEFAULT 1,
        discount      REAL DEFAULT 0,
        PRIMARY KEY (order_id, product_id)
    );
    """)

    c.executemany('INSERT INTO categories VALUES (?,?,?)', [
        (1, 'Beverages',   'Soft drinks, coffees, teas, beers and ales'),
        (2, 'Condiments',  'Sweet and savory sauces, relishes, spreads and seasonings'),
        (3, 'Dairy',       'Cheeses and other dairy products'),
        (4, 'Grains',      'Breads, crackers, pasta and cereal'),
        (5, 'Meat',        'Prepared meats and poultry'),
        (6, 'Produce',     'Dried fruit and bean curd'),
        (7, 'Seafood',     'Seaweed and fish'),
        (8, 'Confections', 'Desserts, candies and sweet breads'),
    ])

    c.executemany('INSERT INTO suppliers VALUES (?,?,?,?,?,?)', [
        (1, 'Exotic Liquids',        'Charlotte Cooper', 'UK',      'London',    '(171) 555-2222'),
        (2, 'New Orleans Cajun',     'Shelley Burke',    'USA',     'New Orleans','(100) 555-4822'),
        (3, 'Grandma Kelly\'s',      'Regina Murphy',    'USA',     'Ann Arbor', '(313) 555-5735'),
        (4, 'Tokyo Traders',         'Yoshi Nagase',     'Japan',   'Tokyo',     '(03) 3555-5011'),
        (5, 'Cooperativa de Quesos', 'Antonio del Valle','Spain',   'Oviedo',    '(98) 598 76 54'),
        (6, 'Mayumi\'s',             'Mayumi Ohno',      'Japan',   'Osaka',     '(06) 431-7877'),
        (7, 'Pavlova Ltd.',          'Ian Devling',      'Australia','Melbourne', '(03) 444-2343'),
        (8, 'Specialty Biscuits',    'Peter Wilson',     'UK',      'Manchester','(161) 555-4448'),
    ])

    c.executemany('INSERT INTO products VALUES (?,?,?,?,?,?,?)', [
        (1,  'Chai',              1, 1, 18.00,  39, 0),
        (2,  'Chang',             1, 1, 19.00,  17, 0),
        (3,  'Aniseed Syrup',     2, 1,  10.00, 13, 0),
        (4,  'Chef Anton\'s',     2, 2,  22.00, 53, 0),
        (5,  'Grandma\'s Boysenberry Spread', 2, 3, 25.00, 120, 0),
        (6,  'Uncle Bob\'s Organic', 6, 3, 30.00, 15, 0),
        (7,  'Northwoods Cranberry', 2, 3, 40.00, 6, 0),
        (8,  'Mishi Kobe Niku',   5, 4, 97.00,  29, 1),
        (9,  'Tofu',              6, 4, 23.25,  35, 0),
        (10, 'Ikura',             7, 4, 31.00,  31, 0),
        (11, 'Queso Cabrales',    3, 5, 21.00,  22, 0),
        (12, 'Queso Manchego',    3, 5, 38.00,  86, 0),
        (13, 'Konbu',             7, 6, 6.00,   24, 0),
        (14, 'Tofu Miso',         6, 6, 23.25,  35, 0),
        (15, 'Genen Shouyu',      2, 6, 15.50,  39, 0),
        (16, 'Pavlova',           8, 7, 17.45, 29,  0),
        (17, 'Alice Mutton',      5, 7, 39.00,  0,  1),
        (18, 'Carnarvon Tigers',  7, 7, 62.50,  42, 0),
        (19, 'Teatime Biscuits',  8, 8, 9.20,   25, 0),
        (20, 'Sir Rodney\'s Marmalade', 8, 8, 81.00, 40, 0),
    ])

    c.executemany('INSERT INTO customers VALUES (?,?,?,?,?,?)', [
        ('ALFKI', 'Alfreds Futterkiste',   'Maria Anders',    'Germany', 'Berlin',    '030-0074321'),
        ('ANATR', 'Ana Trujillo',          'Ana Trujillo',    'Mexico',  'México D.F.','(5) 555-4729'),
        ('ANTON', 'Antonio Moreno',        'Antonio Moreno',  'Mexico',  'México D.F.','(5) 555-3932'),
        ('AROUT', 'Around the Horn',       'Thomas Hardy',    'UK',      'London',    '(171) 555-7788'),
        ('BERGS', 'Berglunds snabbköp',    'Christina Berglund','Sweden','Luleå',     '0921-12 34 65'),
        ('BLAUS', 'Blauer See Delikatessen','Hanna Moos',     'Germany', 'Mannheim',  '0621-08460'),
        ('BONAP', 'Bon app\'',             'Laurence Lebihan','France',  'Marseille', '91.24.45.40'),
        ('BOTTM', 'Bottom-Dollar Markets', 'Elizabeth Lincoln','Canada', 'Tsawwassen','(604) 555-4729'),
        ('BSBEV', 'B\'s Beverages',        'Victoria Ashworth','UK',    'London',     '(171) 555-1212'),
        ('CACTU', 'Cactus Comidas para llevar','Patricio Simpson','Argentina','Buenos Aires','(1) 135-5555'),
    ])

    c.executemany('INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)', [
        (1, 'Nancy',   'Davolio',   'Sales Representative',  '2022-05-01', 'USA', 'Seattle',  None),
        (2, 'Andrew',  'Fuller',    'Vice President, Sales', '2022-08-14', 'USA', 'Tacoma',   None),
        (3, 'Janet',   'Leverling', 'Sales Representative',  '2023-04-01', 'USA', 'Kirkland', 2),
        (4, 'Margaret','Peacock',   'Sales Representative',  '2023-05-03', 'USA', 'Redmond',  2),
        (5, 'Steven',  'Buchanan',  'Sales Manager',         '2023-10-17', 'UK',  'London',   2),
        (6, 'Michael', 'Suyama',    'Sales Representative',  '2024-01-02', 'UK',  'London',   5),
        (7, 'Robert',  'King',      'Sales Representative',  '2024-01-02', 'UK',  'London',   5),
        (8, 'Laura',   'Callahan',  'Inside Sales Coordinator','2024-03-05','USA','Seattle',  2),
        (9, 'Anne',    'Dodsworth', 'Sales Representative',  '2024-11-15', 'UK',  'London',   5),
    ])

    c.executemany('INSERT INTO shippers VALUES (?,?,?)', [
        (1, 'Speedy Express',   '(503) 555-9831'),
        (2, 'United Package',   '(503) 555-3199'),
        (3, 'Federal Shipping', '(503) 555-9931'),
    ])

    orders = [
        (10248, 'VINET', 5, '2024-07-04', '2024-07-16', 3, 32.38, 'France'),
        (10249, 'TOMSP', 6, '2024-07-05', '2024-07-10', 1, 11.61, 'Germany'),
        (10250, 'HANAR', 4, '2024-07-08', '2024-07-12', 2, 65.83, 'Brazil'),
        (10251, 'VICTE', 3, '2024-07-08', '2024-07-15', 1, 41.34, 'France'),
        (10252, 'SUPRD', 4, '2024-07-09', '2024-07-11', 2, 51.30, 'Belgium'),
        (10253, 'HANAR', 3, '2024-07-10', '2024-07-16', 2, 58.17, 'Brazil'),
        (10254, 'CHOPS', 5, '2024-07-11', '2024-07-23', 2, 22.98, 'Switzerland'),
        (10255, 'RICSU', 9, '2024-07-12', '2024-07-15', 3, 148.33,'Switzerland'),
        (10256, 'WELLI', 3, '2024-07-15', '2024-07-17', 2, 13.97, 'Brazil'),
        (10257, 'HILAA', 4, '2024-07-16', '2024-07-22', 3, 81.91, 'Venezuela'),
        (10258, 'ERNSH', 1, '2024-07-17', '2024-07-23', 1, 140.51,'Austria'),
        (10259, 'CENTC', 4, '2024-07-18', '2024-07-25', 3, 3.25,  'Mexico'),
        (10260, 'OTTIK', 4, '2024-07-19', None,         1, 55.09, 'Germany'),
        (10261, 'QUEDE', 4, '2024-07-19', None,         2, 3.05,  'Brazil'),
        (10262, 'RATTC', 8, '2024-07-22', None,         3, 48.29, 'USA'),
    ]
    c.executemany('INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)', orders)

    details = [
        (10248, 11,  14.00, 12, 0), (10248, 42,  9.80, 10, 0),  (10248, 72,  34.80, 5, 0),
        (10249, 14,  18.60, 9,  0), (10249, 51,  42.40, 40, 0),
        (10250, 41,  7.70,  10, 0), (10250, 51,  42.40, 35, 0.15),(10250, 65, 16.80, 15, 0.15),
        (10251, 22,  16.80, 6,  0.05),(10251, 57, 15.60, 15, 0.05),(10251, 65, 16.80, 20, 0),
        (10252, 20,  64.80, 40, 0.05),(10252, 33, 2.00,  25, 0.05),(10252, 60, 27.20, 40, 0),
        (10253, 31,  10.00, 20, 0), (10253, 39,  14.40, 42, 0), (10253, 49, 16.00, 40, 0),
        (10254, 24,  3.60,  15, 0.15),(10254, 55, 19.20, 21, 0.15),(10254, 74, 8.00, 21, 0),
        (10255, 2,   15.20, 20, 0), (10255, 16,  13.90, 35, 0), (10255, 36, 15.20, 25, 0),
        (10256, 53,  26.20, 15, 0), (10256, 77,  10.40, 12, 0),
        (10257, 27,  35.10, 25, 0), (10257, 39,  14.40, 6,  0), (10257, 77, 10.40, 15, 0),
        (10258, 2,   15.20, 50, 0.20),(10258, 5,  17.00, 65, 0.20),(10258, 32, 25.60, 6, 0.20),
        (10259, 21,  8.00,  10, 0), (10259, 37,  20.80, 1,  0),
        (10260, 41,  7.70,  16, 0.25),(10260, 57, 15.60, 50, 0),(10260, 62, 39.40, 15, 0.25),
        (10261, 21,  8.00,  20, 0), (10261, 35,  14.40, 20, 0),
        (10262, 5,   17.00, 12, 0.20),(10262, 7,  24.00, 15, 0),(10262, 56, 30.40, 2, 0),
    ]
    c.executemany('INSERT INTO order_details VALUES (?,?,?,?,?)', details)

    conn.commit()
    conn.close()
