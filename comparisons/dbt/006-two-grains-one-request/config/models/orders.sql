select order_id, shipping, cast(created_at as timestamp) as created_at
from {{ source('bronze', 'corpus__orders') }}
