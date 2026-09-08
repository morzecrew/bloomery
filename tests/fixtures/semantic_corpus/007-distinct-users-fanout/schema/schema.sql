-- An event fact: one row per session, carrying who had it and on which day.
-- Every value is valid and nothing is duplicated; the trap is in the question.
CREATE TABLE bronze.corpus__sessions (
    session_id  VARCHAR,
    user_id     VARCHAR,
    session_day DATE
);
