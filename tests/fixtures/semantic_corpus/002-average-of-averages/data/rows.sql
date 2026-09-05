-- Two orders of very different size. That asymmetry is the whole case: an
-- average of averages weights each *order* equally, and an average of items
-- weights each *item* equally, and they are only the same when every order
-- has the same number of lines.
INSERT INTO corpus.order_items VALUES
    ('o1', 1, 100.00),
    ('o2', 1,  10.00),
    ('o2', 2,  10.00),
    ('o2', 3,  10.00);
