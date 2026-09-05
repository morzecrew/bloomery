-- Two accounts over two days. One moves, one does not — so the wrong answer
-- is not simply "twice the right one", and a reviewer has to do the addition.
INSERT INTO bronze.corpus__balances VALUES
    ('a1', DATE '2025-01-01', 100.00),
    ('a1', DATE '2025-01-02', 120.00),
    ('a2', DATE '2025-01-01',  50.00),
    ('a2', DATE '2025-01-02',  50.00);
