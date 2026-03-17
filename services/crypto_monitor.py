import requests
from datetime import datetime
import base64
import struct

class CryptoMonitor:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def search_tx(self, tx_hash, target_wallet=None):
        """
        Единая точка входа для поиска транзакции.
        Возвращает словарь с данными {symbol, amount, from_addr, to_addr, dt} или None.
        """
        tx_hash = tx_hash.strip()
        clean_hash_lower = tx_hash.lower()
        
        print(f"\n🔍 Запуск анализа хеша: {tx_hash}")

        # 1. Сначала пробуем EVM сети (они начинаются на 0x)
        if tx_hash.startswith("0x"):
            res = (
                self.check_eth_erc20(clean_hash_lower, target_wallet) or
                self.check_base(clean_hash_lower, target_wallet) or
                self.check_bsc(clean_hash_lower, target_wallet) or
                self.check_evm_universal(clean_hash_lower, "arbitrum", target_wallet) or
                self.check_evm_universal(clean_hash_lower, "polygon", target_wallet)
            )
            if res: return res

        # 2. Пробуем остальные сети
        res = (
            self.check_ton(tx_hash) or
            self.check_tron(tx_hash, target_wallet) or
            self.check_bitcoin(tx_hash, target_wallet) or
            self.check_doge(tx_hash, target_wallet) or
            self.check_xmr(tx_hash, target_wallet)
        )
        if res: return res

        print("❌ Транзакция не найдена ни в одной из поддерживаемых сетей.")
        return None

    def _format_result(self, symbol, amount, from_addr, to_addr, dt):
        return {
            "symbol": str(symbol),
            "amount": float(amount),
            "from_addr": str(from_addr),
            "to_addr": str(to_addr),
            "dt": str(dt)
        }

    def print_success(self, chain, symbol, amount, from_addr, to_addr, dt):
        print("\n" + "✅" * 10 + f" НАЙДЕНО В {chain.upper()} " + "✅" * 10)
        print(f"КРИПТА:   {symbol}")
        print(f"СУММА:    {amount}")
        print(f"ОТКУДА:   {from_addr}")
        print(f"КУДА:     {to_addr}")
        print(f"ДАТА:     {dt}")
        print("=" * 45)

    def raw_to_friendly(self, raw_addr):
        """Конвертирует адрес из 0:abc в формат UQ... (Non-bounceable)"""
        if not raw_addr or ":" not in raw_addr:
            return raw_addr
        try:
            workchain, address_hex = raw_addr.split(":")
            workchain = int(workchain)
            address_bytes = bytes.fromhex(address_hex)
            
            # 0x51 - это префикс для Non-bounceable (начинаются на UQ)
            # Именно его используют современные кошельки по умолчанию
            tag = 0x51 
            chain_id = workchain & 0xFF
            
            data = struct.pack("BB", tag, chain_id) + address_bytes
            
            # Вычисление CRC16 (контрольная сумма)
            crc = 0
            for byte in data:
                crc ^= (byte << 8)
                for _ in range(8):
                    if crc & 0x8000:
                        crc = (crc << 1) ^ 0x1021
                    else:
                        crc <<= 1
            crc &= 0xFFFF
            
            full_data = data + struct.pack(">H", crc)
            # Используем urlsafe base64
            res = base64.urlsafe_b64encode(full_data).decode().replace("=", "")
            return res
        except:
            return raw_addr

    def check_ton(self, tx_hash):
        import urllib.parse
        
        url = f"https://tonapi.io/v2/events/{urllib.parse.quote(tx_hash)}"
        print(f"  [LOG] Проверка в TON...")
        
        try:
            res = requests.get(url, headers=self.headers, timeout=15)
            if res.status_code != 200: return None
            data = res.json()
            actions = data.get("actions", [])
            if not actions: return None

            for action in actions:
                action_type = action.get("type")
                details = action.get("TonTransfer") or action.get("JettonTransfer") or \
                          action.get("ton_transfer") or action.get("jetton_transfer")
                
                if details:
                    # Определяем символ и количество знаков после запятой
                    symbol, decimals = "TON", 9
                    if action_type == "JettonTransfer":
                        j_info = details.get("jetton", {})
                        symbol = j_info.get("symbol", "TOKEN")
                        decimals = j_info.get("decimals", 9)

                    amount = int(details.get("amount", 0)) / 10**decimals
                    
                    # Получаем адреса (используем ваш метод raw_to_friendly для красоты)
                    s_info = details.get("sender", {})
                    r_info = details.get("recipient", {})

                    from_addr = s_info.get("user_friendly") or s_info.get("name") or self.raw_to_friendly(s_info.get("address"))
                    to_addr = r_info.get("user_friendly") or r_info.get("name") or self.raw_to_friendly(r_info.get("address"))
                    
                    dt = datetime.fromtimestamp(data.get("timestamp", 0)).strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Возвращаем словарь для main.py вместо вывода в консоль
                    return self._format_result(
                        symbol=symbol,
                        amount=amount,
                        from_addr=from_addr,
                        to_addr=to_addr,
                        dt=dt
                    )

            return None
        except Exception as e:
            print(f"  [LOG] TON Error: {e}")
            return None

    def check_doge(self, tx_hash, target_wallet=None):
        """Парсинг Dogecoin через Blockchair, возвращает словарь с данными или None"""
        url = f"https://api.blockchair.com/dogecoin/dashboards/transaction/{tx_hash}"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code != 200: 
                return None
            
            data = res.json()["data"].get(tx_hash)
            if not data: 
                return None
            
            tx = data["transaction"]
            outputs = data.get("outputs", [])
            
            found_amount = 0
            final_to_addr = ""

            if target_wallet:
                # Считаем сумму только для конкретного кошелька
                for out in outputs:
                    if out.get("recipient") == target_wallet:
                        found_amount += out.get("value", 0)
                final_to_addr = target_wallet if found_amount > 0 else "Address not found"
            else:
                # Если кошелек не задан, берем первый выход
                found_amount = sum(out.get("value", 0) for out in outputs)
                final_to_addr = outputs[0].get("recipient") if outputs else "N/A"

            # DOGE имеет 8 знаков после запятой
            amount_doge = found_amount / 100_000_000 
            
            # Если сумма 0 (транзакция есть, но на этот адрес ничего не пришло), возвращаем None
            if amount_doge <= 0:
                return None

            from_addr = data.get("inputs", [{}])[0].get("recipient", "N/A")
            dt = tx.get("time", "N/A")

            # Возвращаем словарь через ваш метод _format_result
            return self._format_result(
                symbol="DOGE",
                amount=amount_doge,
                from_addr=from_addr,
                to_addr=final_to_addr,
                dt=dt
            )
        except Exception as e:
            print(f"  [LOG] DOGE Error: {e}")
            return None

    def check_eth_erc20(self, tx_hash, target_wallet=None):
        """Парсинг Ethereum и ERC-20, возвращает словарь с данными или None"""
        print(f"  [LOG] Проверка в ETH/ERC-20...")
        
        # 1. Пробуем Ethplorer (лучше всего для токенов)
        url_ethplorer = f"https://api.ethplorer.io/getTxInfo/{tx_hash}?apiKey=freekey"
        try:
            res = requests.get(url_ethplorer, timeout=10)
            data = res.json()
            
            if "hash" in data:
                symbol = "ETH"
                amount = 0
                from_addr = data.get("from")
                to_addr = data.get("to")
                
                # Если это перевод токена
                if "operations" in data and len(data["operations"]) > 0:
                    op = data["operations"][0]
                    symbol = op["tokenInfo"]["symbol"]
                    amount = int(op["value"]) / (10 ** int(op["tokenInfo"]["decimals"]))
                    from_addr = op["from"]
                    to_addr = op["to"]
                else:
                    # Если это обычный перевод ETH
                    amount = data.get("value", 0)

                # Если указан кошелек, проверяем, что перевод именно на него
                if target_wallet and to_addr.lower() != target_wallet.lower():
                    return None
                
                dt = datetime.fromtimestamp(data.get("timestamp")).strftime('%Y-%m-%d %H:%M:%S')
                
                return self._format_result(symbol, amount, from_addr, to_addr, dt)
        except Exception as e:
            print(f"  [LOG] Ethplorer Error: {e}")

        # 2. Резерв: Пробуем Blockchair
        url_bc = f"https://api.blockchair.com/ethereum/dashboards/transaction/{tx_hash}"
        try:
            res = requests.get(url_bc, headers=self.headers, timeout=10)
            if res.status_code == 200:
                data = res.json()["data"][tx_hash]
                tx = data["transaction"]
                
                # Проверка для ETH
                to_addr = tx.get("recipient")
                if target_wallet and to_addr.lower() != target_wallet.lower():
                    return None
                
                return self._format_result(
                    symbol="ETH",
                    amount=int(tx["value"]) / 10**18,
                    from_addr=tx.get("sender"),
                    to_addr=to_addr,
                    dt=tx.get("time")
                )
        except Exception as e:
            print(f"  [LOG] Blockchair ETH Error: {e}")
            
        return None

    def check_evm_universal(self, tx_hash, network="base", target_wallet=None):
        """
        Универсальный поиск для EVM сетей через Blockchair.
        network: 'base', 'arbitrum', 'ethereum', 'polygon', 'binance-smart-chain' и т.д.
        """
        url = f"https://api.blockchair.com/{network}/dashboards/transaction/{tx_hash}"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code != 200: 
                return None
            
            data = res.json()["data"][tx_hash]
            tx = data["transaction"]
            
            # Инициализация переменных
            symbol = "ETH"
            amount = 0
            to_addr = tx.get("recipient")
            from_addr = tx.get("sender")
            dt = tx.get("time")

            # 1. Проверка на ERC-20 токены
            if data.get("layer_2") and "erc_20" in data["layer_2"] and data["layer_2"]["erc_20"]:
                token = data["layer_2"]["erc_20"][0]
                symbol = token["token_symbol"]
                amount = int(token["value"]) / (10 ** token["token_decimals"])
                to_addr = token["recipient"]
            else:
                # 2. Обычный перевод нативной валюты (ETH, BNB, MATIC и т.д.)
                amount = int(tx["value"]) / 10**18
                symbol = network.upper()

            # Проверка, что транзакция была именно на наш целевой кошелек
            if target_wallet and to_addr.lower() != target_wallet.lower():
                return None

            # Если сумма 0 (например, просто вызов контракта без перевода), возвращаем None
            if amount <= 0:
                return None

            return self._format_result(
                symbol=symbol,
                amount=amount,
                from_addr=from_addr,
                to_addr=to_addr,
                dt=dt
            )
        except Exception as e:
            print(f"  [LOG] EVM {network} Error: {e}")
            return None

    def check_base(self, tx_hash, target_wallet=None):
        """Парсинг сети BASE через Blockchair, возвращает словарь с данными или None"""
        print(f"  [LOG] Проверка в BASE...")
        url = f"https://api.blockchair.com/base/dashboards/transaction/{tx_hash}"
        
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code != 200:
                return None
            
            data = res.json()["data"].get(tx_hash)
            if not data:
                return None
            
            tx = data["transaction"]
            
            # Инициализация переменных
            symbol = "ETH (Base)"
            amount = 0
            to_addr = tx.get("recipient")
            from_addr = tx.get("sender")
            dt = tx.get("time")

            # 1. Проверка на токены (ERC-20)
            if data.get("layer_2") and "erc_20" in data["layer_2"] and data["layer_2"]["erc_20"]:
                token = data["layer_2"]["erc_20"][0]
                symbol = token["token_symbol"]
                amount = int(token["value"]) / (10 ** token["token_decimals"])
                to_addr = token["recipient"]
            else:
                # 2. Нативный перевод ETH в сети Base
                amount = int(tx["value"]) / 10**18

            # Безопасность: сверяем кошелек получателя
            if target_wallet and to_addr.lower() != target_wallet.lower():
                return None
            
            # Проверка на нулевую транзакцию
            if amount <= 0:
                return None

            return self._format_result(
                symbol=symbol,
                amount=amount,
                from_addr=from_addr,
                to_addr=to_addr,
                dt=dt
            )
        except Exception as e:
            print(f"  [LOG] BASE Error: {e}")
            return None

    def check_bsc(self, tx_hash, target_wallet=None):
        """Парсинг сети BSC (BNB Smart Chain) через Blockchair"""
        url = f"https://api.blockchair.com/binance-smart-chain/dashboards/transaction/{tx_hash}"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code != 200:
                return None
            
            data = res.json()["data"].get(tx_hash)
            if not data:
                return None
            
            tx = data["transaction"]
            
            # Инициализация переменных
            symbol = "BNB"
            amount = 0
            to_addr = tx.get("recipient")
            from_addr = tx.get("sender")
            dt = tx.get("time")

            # 1. Проверка на токены BEP-20
            if data.get("layer_2") and "erc_20" in data["layer_2"] and data["layer_2"]["erc_20"]:
                token = data["layer_2"]["erc_20"][0]
                symbol = token["token_symbol"]
                amount = int(token["value"]) / (10 ** token["token_decimals"])
                to_addr = token["recipient"]
            else:
                # 2. Нативный перевод BNB
                amount = int(tx["value"]) / 10**18

            # Безопасность: сверяем кошелек получателя (регистр не важен)
            if target_wallet and to_addr.lower() != target_wallet.lower():
                return None
            
            # Проверка на пустую транзакцию
            if amount <= 0:
                return None

            return self._format_result(
                symbol=symbol,
                amount=amount,
                from_addr=from_addr,
                to_addr=to_addr,
                dt=dt
            )
        except Exception as e:
            print(f"  [LOG] BSC Error: {e}")
            return None

    def check_xmr(self, tx_hash, target_wallet=None):
        """
        Проверка Monero через публичные API.
        ВНИМАНИЕ: Сумма и адреса в XMR скрыты, возвращаем "HIDDEN".
        """
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        print(f"  [LOG] Проверка в Monero (XMR)...")
        
        # Список доступных API для Monero
        providers = [
            {"name": "Monero.ovh", "url": f"https://explorer.monero.ovh/api/transaction/{tx_hash}"},
            {"name": "XMRScan", "url": f"https://xmrscan.org/api/v1/tx/{tx_hash}"}
        ]
        
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        
        for api in providers:
            try:
                res = requests.get(api["url"], headers=headers, timeout=15, verify=False)
                
                if res.status_code == 200:
                    data = res.json()
                    # У разных API разная структура ответа
                    tx_data = data.get("data", {})
                    if not tx_data: continue
                    
                    timestamp = tx_data.get("timestamp")
                    if timestamp:
                        dt = datetime.fromtimestamp(int(timestamp)).strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Возвращаем данные. 
                        # Так как XMR конфиденциален, для суммы и адресов ставим заглушки
                        return self._format_result(
                            symbol="XMR",
                            amount=0.0, # Невозможно определить публично
                            from_addr="CONFIDENTIAL",
                            to_addr="CONFIDENTIAL",
                            dt=dt
                        )
            except Exception as e:
                print(f"  [LOG] XMR {api['name']} error: {e}")
                continue

        return None

    def check_tron(self, tx_hash, target_wallet=None):
        """Парсинг сети TRON, возвращает словарь с данными или None"""
        url = f"https://apilist.tronscan.org/api/transaction-info?hash={tx_hash}"
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            if res.status_code != 200: return None
            data = res.json()
            
            if "hash" not in data: return None

            symbol = "TRX"
            amount = 0
            # Извлекаем адреса из корня или contractData
            from_addr = data.get("ownerAddress") or data.get("fromAddress", "N/A")
            to_addr = data.get("toAddress") or data.get("contractData", {}).get("to_address", "N/A")

            # 1. Проверка на TRC-20 токены (USDT, USDC и т.д.)
            if data.get("trc20TransferInfo"):
                ti = data["trc20TransferInfo"][0]
                symbol = ti.get("symbol", "TOKEN")
                decimals = int(ti.get("decimals", 6))
                amount = int(ti.get("amount_str", 0)) / (10 ** decimals)
                to_addr = ti.get("to_address")
                from_addr = ti.get("from_address")
            
            # 2. Проверка на нативный TRX
            else:
                c_data = data.get("contractData", {})
                if isinstance(c_data, dict) and "amount" in c_data:
                    amount = int(c_data["amount"]) / 1_000_000
                elif data.get("amount"):
                    amount = int(data.get("amount", 0)) / 1_000_000

            # Безопасность: сверяем кошелек получателя
            # В TRON адреса обычно имеют разный формат (T... или 41...), 
            # но Tronscan отдает их в стандарте T...
            if target_wallet and to_addr != target_wallet:
                # Если адреса разные, транзакция нам не подходит
                return None

            if amount <= 0: return None

            # Преобразование времени (в TRON в миллисекундах)
            timestamp = data.get("timestamp", 0)
            dt = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')

            return self._format_result(
                symbol=symbol,
                amount=amount,
                from_addr=from_addr,
                to_addr=to_addr,
                dt=dt
            )
        except Exception as e:
            print(f"  [LOG] TRON Error: {e}")
            return None

    def check_bitcoin(self, tx_hash, target_wallet=None):
        """Парсинг Bitcoin через Blockchain.info, возвращает словарь с данными или None"""
        url = f"https://blockchain.info/rawtx/{tx_hash}"
        try:
            res = requests.get(url, timeout=10)
            if res.status_code != 200:
                return None
            
            data = res.json()
            outputs = data.get('out', [])
            inputs = data.get('inputs', [])
            
            # Если кошелек указан, ищем сумму только для него
            if target_wallet:
                found_amount = sum(out.get('value', 0) for out in outputs if out.get('addr') == target_wallet)
                to_addr = target_wallet
            else:
                # Если кошелек не указан, берем общую сумму всех выходов
                found_amount = sum(out.get('value', 0) for out in outputs)
                to_addr = outputs[0].get('addr') if outputs else "N/A"

            # BTC имеет 8 знаков после запятой (1 satoshi = 0.00000001 BTC)
            amount_btc = found_amount / 10**8
            
            # Если сумма 0 (транзакция есть, но на наш кошелек не пришло ничего), возвращаем None
            if amount_btc <= 0:
                return None

            from_addr = inputs[0].get('prev_out', {}).get('addr', "N/A") if inputs else "N/A"
            dt = datetime.fromtimestamp(data.get("time")).strftime('%Y-%m-%d %H:%M:%S')

            return self._format_result(
                symbol="BTC",
                amount=amount_btc,
                from_addr=from_addr,
                to_addr=to_addr,
                dt=dt
            )
        except Exception as e:
            print(f"  [LOG] Bitcoin Error: {e}")
            return None
