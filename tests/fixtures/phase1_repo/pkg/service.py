import os
from web.widget import renderWidget


class Service:
    def run(self) -> str:
        return renderWidget("Aksi")


def make_service() -> Service:
    return Service()
