-- The project-authored reading of the inclusive metric: every shipment's cost
-- over every shipment's parcels, cancelled ones included. dbt Core renders no
-- SQL for a metric, so this model is what produces the number.
select round(sum(carrier_cost) / sum(parcels), 2) as cost_per_parcel
from {{ ref('shipments') }}
