-- Three customers over two days of one month. `c1` buys on both days, which is
-- what makes the daily counts sum to more customers than there are.
INSERT INTO bronze.corpus__orders VALUES
    ('o1', 'c1', 40.00, DATE '2025-01-06'),
    ('o2', 'c2', 25.00, DATE '2025-01-06'),
    ('o3', 'c1', 15.00, DATE '2025-01-07'),
    ('o4', 'c3', 30.00, DATE '2025-01-07');
