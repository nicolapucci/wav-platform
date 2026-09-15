from fastapi import FastAPI

from .routers import boards, comments, layers, me, organizations, permissions, projects, tags, tasks, teams, users

app = FastAPI(title="api-service")

app.include_router(organizations.router)
app.include_router(teams.router)
app.include_router(projects.router)
app.include_router(layers.router)
app.include_router(tasks.router)
app.include_router(comments.router)
app.include_router(boards.router)
app.include_router(me.router)
app.include_router(permissions.router)
app.include_router(users.router)
app.include_router(tags.router)


@app.get("/health")
def health():
    return {"status": "ok"}
