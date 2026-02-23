from pydantic import BaseModel, ConfigDict
from typing import Optional, Union, Any

class TransactionData(BaseModel):
    city_id: Union[int, str]
    brand_id: Optional[Union[int, str]] = None
    creator_id: Optional[Union[int, str]] = None
    visit_time: Optional[str] = ""
    transaction_type: Optional[str] = "direct"
    client_full_name: Optional[str] = "Не указано"
    cash_amount: Any = 0
    cash_currency: Optional[str] = ""
    wallet_address: Optional[str] = ""
    wallet_network: Optional[str] = ""
    wallet_amount: Any = 0
    wallet_currency: Optional[str] = ""
    wallet_owner_type: Optional[str] = ""
    form_url: Optional[str] = ""
    model_config = ConfigDict(extra="allow")

class CalculationData(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    transaction_type: str        
    calculation_type: str        
    operator_rate: Any 
    total_percentage: Any 
    client_rate: Any
    fee: Any                    
    formula: Optional[str] = ""                 
    total_to_transfer: Any       
    test_info: Optional[str] = "Без теста"
    model_config = ConfigDict(extra="allow")

class StatusUpdateData(BaseModel):
    chat_id: Union[int, str]
    message_thread_id: Union[int, str]
    text: str
    operator_name: Optional[str] = "Система"
    link: Optional[str] = None 
    model_config = ConfigDict(extra="allow")