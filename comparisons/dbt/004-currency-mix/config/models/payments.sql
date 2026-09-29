select payment_id, amount_eur, fee_usd, cast(paid_at as timestamp) as paid_at
from {{ source('bronze', 'corpus__payments') }}
