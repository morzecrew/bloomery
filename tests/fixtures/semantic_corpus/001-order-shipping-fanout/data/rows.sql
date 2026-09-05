-- One order, three lines. Small enough to check by eye (RFC 0042 D2):
-- shipping is 9.00 once, and 27.00 if you count it per line.
INSERT INTO corpus.orders VALUES ('o1', 9.00);

INSERT INTO corpus.order_items VALUES
    ('o1', 1, 10.00),
    ('o1', 2, 10.00),
    ('o1', 3, 10.00);
