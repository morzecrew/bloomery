-- One customer who was upgraded once, and two orders — one on each side of
-- the change.
INSERT INTO corpus.orders VALUES
    ('o1', 'c1', TIMESTAMP '2025-03-01 00:00:00', 100.00),
    ('o2', 'c1', TIMESTAMP '2025-09-01 00:00:00', 200.00);

INSERT INTO corpus.customer_tier VALUES
    ('c1', 'bronze', TIMESTAMP '2025-01-01 00:00:00', TIMESTAMP '2025-06-01 00:00:00'),
    ('c1', 'gold',   TIMESTAMP '2025-06-01 00:00:00', TIMESTAMP '9999-12-31 00:00:00');
