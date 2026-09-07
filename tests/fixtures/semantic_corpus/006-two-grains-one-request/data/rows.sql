-- Three orders and six lines, small enough to check by eye (RFC 0042 D2).
-- Shipping is 9 + 5 + 2 = 16.00 once, and 27 + 5 + 4 = 36.00 counted per line.
-- Discount is 3 * 1.00 + 2.00 + 2 * 0.50 = 6.00 either way, which is the half
-- of the naive answer that is right.
INSERT INTO bronze.corpus__orders VALUES
    ('o1', 9.00, '2025-03-01T00:00:00'),
    ('o2', 5.00, '2025-03-01T00:00:00'),
    ('o3', 2.00, '2025-03-01T00:00:00');

INSERT INTO bronze.corpus__order_items VALUES
    ('o1', 1, 1.00, '2025-03-01T00:00:00'),
    ('o1', 2, 1.00, '2025-03-01T00:00:00'),
    ('o1', 3, 1.00, '2025-03-01T00:00:00'),
    ('o2', 1, 2.00, '2025-03-01T00:00:00'),
    ('o3', 1, 0.50, '2025-03-01T00:00:00'),
    ('o3', 2, 0.50, '2025-03-01T00:00:00');
