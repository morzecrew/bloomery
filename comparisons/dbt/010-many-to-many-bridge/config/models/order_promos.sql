select order_id, promo_id, cast(applied_on as timestamp) as applied_on
from {{ source('bronze', 'corpus__order_promos') }}
