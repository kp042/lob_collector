from dataclasses import dataclass
from environs import Env
import json

@dataclass
class VpsData:
    main_ip: str
    second_ip: str

@dataclass
class KafkaData:
    kafka_broker: str
    kafka_topic: str

@dataclass
class Exceptions:
    coins: list[str]

@dataclass
class Config:
    ip: VpsData
    kafka: KafkaData
    exceptions: Exceptions


def get_exception_list():
    try:
        with open("exceptions.json", 'r') as f:
            return json.load(f).get("exceptions", [])
    except Exception as e:
        raise 


def load_config(path: str | None = None) -> Config:
    env = Env()
    env.read_env(path)
    return Config(
        ip=VpsData(
            main_ip=env("MAIN_IP"),
            second_ip=env("ADDITIONAL_IP")
        ),
        kafka=KafkaData(
            kafka_broker=env("KAFKA_BROKER"),
            kafka_topic=env("KAFKA_TOPIC")
        ),
        exceptions=Exceptions(coins=get_exception_list())
    )


config: Config = load_config()
