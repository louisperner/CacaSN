import tempfile
import unittest
from unittest import mock

from caca_sn import alertas

NOVO = {"oid": "ZTF26a", "nota": 20.0, "conhecido": "NÃO está no TNS — dá para reportar"}


class TesteAlertas(unittest.TestCase):
    def test_avisa_uma_vez(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(alertas, "notificar") as n:
            self.assertEqual(len(alertas.avisar_novos([NOVO], d)), 1)
            self.assertEqual(alertas.avisar_novos([NOVO], d), [])
        self.assertEqual(n.call_count, 1)

    def test_ignora_abaixo_do_corte_e_ja_reportado(self):
        itens = [dict(NOVO, oid="b", nota=alertas.AVISO - 0.1), dict(NOVO, oid="c", conhecido="TNS: AT 2026x")]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(alertas, "notificar") as n:
            self.assertEqual(alertas.avisar_novos(itens, d), [])
        n.assert_not_called()

    def test_fora_do_macos_nao_chama_osascript(self):
        with mock.patch.object(alertas.sys, "platform", "linux"), mock.patch.object(alertas.subprocess, "run") as run:
            alertas.notificar("t", "x", "r.html")
        run.assert_not_called()


class TesteAprovacao(unittest.TestCase):
    def janela(self, saida, codigo=0):
        r = mock.Mock(returncode=codigo, stdout=saida)
        with mock.patch.object(alertas.sys, "platform", "darwin"), mock.patch.object(alertas.subprocess, "run", return_value=r):
            return alertas.pedir_aprovacao("t", "x")

    def test_so_o_clique_em_enviar_aprova(self):
        self.assertTrue(self.janela("button returned:Enviar ao TNS, gave up:false"))
        self.assertFalse(self.janela("button returned:Depois, gave up:false"))
        self.assertFalse(self.janela("button returned:Depois, gave up:true"))  # ninguém respondeu
        self.assertFalse(self.janela("", codigo=1))  # janela fechada / erro

    def test_fora_do_macos_nunca_aprova(self):
        with mock.patch.object(alertas.sys, "platform", "linux"):
            self.assertFalse(alertas.pedir_aprovacao("t", "x"))


if __name__ == "__main__":
    unittest.main()
