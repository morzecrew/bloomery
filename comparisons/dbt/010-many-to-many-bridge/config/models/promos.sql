select promo_id, label
from {{ source('bronze', 'corpus__promos') }}
