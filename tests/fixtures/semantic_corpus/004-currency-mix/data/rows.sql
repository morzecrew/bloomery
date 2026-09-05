-- Two payments, one rate period. 100 EUR at 1.10 is 110 USD.
INSERT INTO bronze.corpus__payments VALUES
    ('p1', 100.00, 5.00, DATE '2025-03-01'),
    ('p2',  50.00, 2.50, DATE '2025-03-02');

INSERT INTO silver.fx_rate VALUES
    ('EUR', 'USD', 1.10000000, DATE '2025-01-01', DATE '9999-12-31');
