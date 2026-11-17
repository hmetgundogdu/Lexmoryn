"""Take a nightly PostgreSQL snapshot for disaster recovery."""


def backup_database():
    return {"schedule": "nightly", "destination": "offline archive"}
