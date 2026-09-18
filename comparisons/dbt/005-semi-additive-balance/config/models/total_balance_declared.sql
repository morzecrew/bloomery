-- The project-authored reading of the semi-additive metric: time is selected
-- before the sum, never aggregated by it.
select sum(balance) as total_balance
from {{ ref('balances') }}
where as_of_day = (select max(as_of_day) from {{ ref('balances') }})
