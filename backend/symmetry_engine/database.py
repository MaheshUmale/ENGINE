from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
from config import SYMMETRY_DB_PATH as DB_PATH

Base = declarative_base()

class Candle(Base):
    __tablename__ = 'candles'
    id = Column(Integer, primary_key=True)
    instrument_key = Column(String)
    interval = Column(Integer)
    timestamp = Column(DateTime)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)

class ReferenceLevel(Base):
    __tablename__ = 'reference_levels'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime)
    index_name = Column(String)
    type = Column(String)  # 'High' or 'Low'
    index_price = Column(Float)
    ce_price = Column(Float)
    pe_price = Column(Float)
    instrument_ce = Column(String)
    instrument_pe = Column(String)

class Signal(Base):
    __tablename__ = 'signals'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime)
    index_name = Column(String)
    side = Column(String)  # 'BUY_CE' or 'BUY_PE'
    index_price = Column(Float)
    option_price = Column(Float)
    confluence_score = Column(Integer)
    details = Column(JSON)

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime)
    index_name = Column(String)
    instrument_key = Column(String)
    instrument_ce = Column(String)
    instrument_pe = Column(String)
    side = Column(String)  # 'BUY' or 'SELL'
    price = Column(Float)
    index_price = Column(Float)
    quantity = Column(Integer)
    status = Column(String)  # 'OPEN', 'CLOSED'
    pnl = Column(Float, default=0.0)
    exit_price = Column(Float, default=0.0)
    trailing_sl = Column(Float, default=0.0)

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    message = Column(String)
    is_read = Column(Boolean, default=False)

class AppSetting(Base):
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(String)

engine = create_engine(f'sqlite:///{DB_PATH}')
Session = sessionmaker(bind=engine)

def migrate_db():
    """
    Manually add missing columns to the trades table if they don't exist.
    SqlAlchemy create_all doesn't handle migrations.
    """
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            # Check for columns in trades table
            res = conn.execute(text("PRAGMA table_info(trades)"))
            columns = [row[1] for row in res]

            required_columns = {
                'instrument_ce': 'VARCHAR',
                'instrument_pe': 'VARCHAR',
                'exit_price': 'FLOAT DEFAULT 0.0',
                'trailing_sl': 'FLOAT DEFAULT 0.0'
            }

            for col, col_type in required_columns.items():
                if col not in columns:
                    print(f"Migration: Adding missing column {col} to trades table...")
                    conn.execute(text(f"ALTER TABLE trades ADD COLUMN {col} {col_type}"))
    except Exception as e:
        print(f"Migration Error: {e}")

def init_db():
    import os
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    Base.metadata.create_all(engine)
    try:
        migrate_db()
    except Exception as e:
        print(f"Migration failed: {e}")

def get_session():
    return Session()
