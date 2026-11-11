from fastapi import FastAPI
from app.core.database import db_pool, init_db
from app.routers import web

app = FastAPI(title="Sistema Relacional de Ventas - SOLID")

app.include_router(web.router)

@app.on_event("startup")
def startup_event():
    db_pool.initialize()
    init_db()

@app.on_event("shutdown")
def shutdown_event():
    db_pool.close_all()
