-- The store runs on America/New_York. o1 was placed at 21:30 on 31 January
-- local, which is 02:30 on 1 February UTC — a February order that reads as a
-- January one to anything that takes the string at face value.
INSERT INTO bronze.corpus__orders VALUES
    ('o1', 100.00, '2025-01-31 21:30:00'),
    ('o2',  40.00, '2025-02-15 10:00:00');
