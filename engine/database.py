from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
from .config import DB_PATH

Base = declarative_base()

class RawTick(Base):
    __tablename__ = 'raw_ticks'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    instrument_key = Column(String)
    ltp = Column(Float)
    volume = Column(Float)
    oi = Column(Float)

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
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
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
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    index_name = Column(String)
    side = Column(String)  # 'BUY_CE' or 'BUY_PE'
    index_price = Column(Float)
    option_price = Column(Float)
    confluence_score = Column(Integer)
    details = Column(JSON)

class Trade(Base):
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    index_name = Column(String)
    instrument_key = Column(String)
    side = Column(String)  # 'BUY' or 'SELL'
    price = Column(Float)
    quantity = Column(Integer)
    status = Column(String)  # 'OPEN', 'CLOSED'
    pnl = Column(Float, default=0.0)

engine = create_engine(f'sqlite:///{DB_PATH}')
Session = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)

def get_session():
    return Session()
