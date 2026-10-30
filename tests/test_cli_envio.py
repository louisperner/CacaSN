import json
import os
import tempfile
import unittest
from unittest import mock

from caca_sn import catalogos, cli, envio, ficha

IT = {
    "oid": "ZTF26x",
    "ra": 157.5,
    "dec": 8.1,
    "mjd0": 61338.5,
    "mag": 18.9,
    "fonte": "ztf",
    "conhecido": "NÃO está no TNS",
    "curva": [(0.0, 2, 18.9)],
}
CFG = {"bot_id": 1, "bot_name": "b", "api_key": "k", "reporting_groupid": "216", "reporter": "A. Pessoa"}
PRONTA = {"oid": "ZTF26x", "ra": 157.5, "dec": 8.1, "mag": 18.9, "pronto": True, "motivos": [], "falhas": {}}
PRONTA["nao_deteccao"] = {"mjd": 61320.0, "fid": 2, "limite": 19.2}


class TesteEnviarPedeConfirmacao(unittest.TestCase):
    def rodar(self, resposta, f=PRONTA):
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(catalogos, "tns_carregar", return_value=CFG),
            mock.patch.object(ficha, "montar", return_value=f),
            mock.patch.object(envio, "enviar", return_value={"ok": True, "nome": "2026zzz", "report_id": 1, "erros": []}) as env,
            mock.patch("builtins.print"),
        ):
            with open(os.path.join(d, "resultados.json"), "w") as arq:
                json.dump([IT], arq)
            codigo = cli.enviar("ZTF26x", pasta=d, perguntar=lambda msg: resposta)
            acompanhados = (
                json.load(open(os.path.join(d, "acompanhar.json"))) if os.path.exists(os.path.join(d, "acompanhar.json")) else {}
            )
        return codigo, env, acompanhados

    def test_sem_confirmar_nao_envia(self):
        for resposta in ("", "s", "sim", "ztf26x"):
            codigo, env, _ = self.rodar(resposta)
            self.assertEqual(codigo, 1)
            env.assert_not_called()

    def test_confirmado_envia_e_passa_a_acompanhar(self):
        codigo, env, acompanhados = self.rodar("ZTF26x")
        self.assertEqual(codigo, 0)
        env.assert_called_once()
        self.assertIn("2026zzz", acompanhados)

    def test_ficha_com_motivo_nunca_pergunta(self):
        ruim = dict(PRONTA, pronto=False, motivos=["já está no TNS: 2026ahcq"])
        codigo, env, _ = self.rodar("ZTF26x", ruim)
        self.assertEqual(codigo, 1)
        env.assert_not_called()


class TesteOferecerEnvio(unittest.TestCase):
    def rodar(self, cfg, clique, f=PRONTA):
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(catalogos, "tns_carregar", return_value=cfg),
            mock.patch.object(ficha, "montar", return_value=f),
            mock.patch.object(envio, "enviar", return_value={"ok": True, "nome": "2026zzz", "report_id": 1, "erros": []}) as env,
            mock.patch.object(cli.alertas, "notificar"),
        ):
            with open(os.path.join(d, "resultados.json"), "w") as arq:
                json.dump([IT], arq)
            janelas = []
            nomes = cli.oferecer_envio([IT], d, aprovar=lambda t, x: janelas.append(t) or clique)
        return nomes, env, janelas

    def test_desligado_por_padrao(self):
        nomes, env, janelas = self.rodar(CFG, True)
        self.assertEqual((nomes, janelas), ([], []))
        env.assert_not_called()

    def test_depois_ou_sem_resposta_nao_envia(self):
        nomes, env, janelas = self.rodar(dict(CFG, aprovar_por_dialogo=True), False)
        self.assertEqual(len(janelas), 1)
        self.assertEqual(nomes, [])
        env.assert_not_called()

    def test_clique_em_enviar_envia(self):
        nomes, env, _ = self.rodar(dict(CFG, aprovar_por_dialogo=True), True)
        self.assertEqual(nomes, ["2026zzz"])
        env.assert_called_once()

    def test_ficha_nao_pronta_nem_pergunta(self):
        ruim = dict(PRONTA, pronto=False, motivos=["só 1 detecção"])
        nomes, env, janelas = self.rodar(dict(CFG, aprovar_por_dialogo=True), True, ruim)
        self.assertEqual(janelas, [])
        env.assert_not_called()


if __name__ == "__main__":
    unittest.main()
