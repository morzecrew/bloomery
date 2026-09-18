select account_id, as_of_day, balance
from {{ source('bronze', 'corpus__balances') }}
