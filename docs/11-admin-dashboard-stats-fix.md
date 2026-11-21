# Admin dashboard PostgreSQL statistics fix

The admin statistics query selected both `item` and `category` while grouping only
by `item`. SQLite accepts this permissively, but PostgreSQL rejects the query.
The admin scan list is loaded through a separate endpoint, which is why the table
could show scan results while KPI cards and charts stayed blank.

The query now groups by both `item` and `category`, making it valid on PostgreSQL.
No user or scan records are modified by this code change.
