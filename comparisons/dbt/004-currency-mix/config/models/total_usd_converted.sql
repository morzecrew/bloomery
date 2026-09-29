-- The project-authored conversion: the EUR side at the rate in force on the
-- payment's own date, and only then added to money already in USD.
select sum(cast(p.amount_eur * r.rate as decimal(12, 4)) + p.fee_usd) as total_usd
from {{ ref('payments') }} as p
join {{ source('silver', 'fx_rate') }} as r
  on r.from_ccy = 'EUR' and r.to_ccy = 'USD'
 and cast(p.paid_at as date) >= r.valid_from and cast(p.paid_at as date) < r.valid_to
