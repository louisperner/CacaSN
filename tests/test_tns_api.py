import io
import json
import unittest
import urllib.error

from caca_sn import tns_api

CFG = {"bot_id": 1, "bot_name": "b", "api_key": "k"}


class Resposta(io.BytesIO):
    def __init__(self, dados, restam="29", reset="60"):
        super().__init__(json.dumps({"data": dados}).encode())
        self.headers = {"x-rate-limit-remaining": restam, "x-rate-limit-reset": reset}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def erro_429(reset="20"):
    return urllib.error.HTTPError("u", 429, "Too Many Requests", {"x-rate-limit-reset": reset}, None)


class Relogio:
    def __init__(self):
        self.t = 0.0
        self.esperas = []

    def agora(self):
        return self.t

    def dormir(self, s):
        self.esperas.append(round(s, 1))
        self.t += s


class TesteLimite(unittest.TestCase):
    def setUp(self):
        tns_api._pausa_ate = 0.0
        self.relogio = Relogio()

    def pedir(self, respostas):
        fila = list(respostas)

        def abrir(req, timeout):
            r = fila.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        return tns_api.pedir(CFG, "object", {"objname": "x"}, abrir=abrir, dormir=self.relogio.dormir, agora=self.relogio.agora)

    def test_sem_aperto_nao_espera(self):
        self.assertEqual(self.pedir([Resposta({"a": 1})]), {"a": 1})
        self.assertEqual(self.relogio.esperas, [])

    def test_quase_no_limite_espera_o_reset_antes_do_proximo(self):
        self.pedir([Resposta({}, restam="1", reset="40")])
        self.pedir([Resposta({})])
        self.assertEqual(self.relogio.esperas, [41.0])

    def test_429_espera_e_tenta_de_novo(self):
        self.assertEqual(self.pedir([erro_429("20"), Resposta({"ok": True})]), {"ok": True})
        self.assertEqual(self.relogio.esperas, [21.0])

    def test_429_tres_vezes_sobe(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.pedir([erro_429(), erro_429(), erro_429()])

    def test_outro_erro_sobe_na_hora(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.pedir([urllib.error.HTTPError("u", 500, "x", {}, None)])

    def test_reset_absurdo_fica_no_teto(self):
        self.pedir([Resposta({}, restam="0", reset="3600")])
        self.pedir([Resposta({})])
        self.assertEqual(self.relogio.esperas, [tns_api.ESPERA_MAX + 1])


if __name__ == "__main__":
    unittest.main()
