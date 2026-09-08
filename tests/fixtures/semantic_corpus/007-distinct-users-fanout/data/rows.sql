-- Three users over two days. One of them is active on both, so the sum of
-- the daily distinct counts is not the number of distinct users.
INSERT INTO bronze.corpus__sessions VALUES
    ('s1', 'u1', DATE '2025-01-01'),
    ('s2', 'u2', DATE '2025-01-01'),
    ('s3', 'u1', DATE '2025-01-02'),
    ('s4', 'u3', DATE '2025-01-02');
