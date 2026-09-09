-- o1 used two promotions and o2 used one. Real revenue is 150.00; a join
-- through the bridge produces three rows and counts o1's 100.00 twice.
INSERT INTO bronze.corpus__orders VALUES
    ('o1', 100.00, DATE '2025-01-01'),
    ('o2',  50.00, DATE '2025-01-02');

INSERT INTO bronze.corpus__promos VALUES
    ('p1', 'spring'),
    ('p2', 'loyalty');

INSERT INTO bronze.corpus__order_promos VALUES
    ('o1', 'p1', DATE '2025-01-01'),
    ('o1', 'p2', DATE '2025-01-01'),
    ('o2', 'p1', DATE '2025-01-02');
