from pydantic import BaseModel
from typing import Optional, Union, Any

class TransactionCreate(BaseModel):
    city_id: Union[int, str]
    brand_id: Optional[Union[int, str]] = None
    visit_time: Optional[str] = ""
    transaction_type: str = "direct"
    client_full_name: str = "Не указано"
    cash_amount: Any = 0
    cash_currency: str = ""
    wallet_address: str = ""
    wallet_network: str = ""
    form_url: str = ""
    individual_conditions: int = 0

class StatusUpdate(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    status: str
    link: Optional[str] = None

class CalculationReport(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    transaction_type: str
    calculation_type: str
    operator_rate: Any
    total_percentage: Any
    client_rate: Any
    fee: Any
    formula: str = ""
    total_to_transfer: Any
    test_info: str = "Без теста"

class DocumentUpload(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: int
    file_url: str