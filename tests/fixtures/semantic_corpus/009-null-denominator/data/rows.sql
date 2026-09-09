-- Two shipments that moved parcels, and one that was cancelled after the
-- carrier had already charged for it. Every value is valid; `parcels` is 0
-- rather than null, because the count is known and it is none.
INSERT INTO bronze.corpus__shipments VALUES
    ('s1', 90.00, 30, DATE '2025-01-01'),
    ('s2', 30.00, 10, DATE '2025-01-02'),
    ('s3', 40.00,  0, DATE '2025-01-03');
