## ecogrid_repo
### Description
...

### Local PostgreSQL

Optionally copy `.env.example` to `.env` and change the development credentials.
The defaults from `.env.example` are also used when `.env` is absent.

```shell
docker compose up -d
docker compose ps
```

Test the connection from inside the container:

```shell
docker compose exec postgres psql -U ecogrid -d ecogrid -c "SELECT 1;"
```

Stop the container without deleting its persistent data:

```shell
docker compose down
```
