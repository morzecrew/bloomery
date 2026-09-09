-- Two orders of very different size. The small one has the better revenue per
-- item, and weighting the two orders equally lets it pull the answer up.
INSERT INTO bronze.corpus__orders VALUES
    ('o1', 90.00, 30, DATE '2025-01-01'),
    ('o2', 40.00, 10, DATE '2025-01-02');
