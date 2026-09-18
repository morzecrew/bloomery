-- The project-authored reading of the restricted metric: both operands over
-- the shipments that moved a parcel, and no others.
select round(sum(carrier_cost) / sum(parcels), 2) as cost_per_parcel
from {{ ref('shipments') }}
where parcels > 0
