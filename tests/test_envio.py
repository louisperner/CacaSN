import unittest

from caca_sn import envio

CFG = {"bot_id": 1, "bot_name": "b", "api_key": "k"}
RECUSA = {
    "id_code": 400,
    "data": {"feedback": {"at_report": [{"reporting_groupid": [{"error_id": 0, "message": "Invalid. DebugNum-134"}]}]}},
}
ACEITA = {
    "id_code": 200,
    "data": {"feedback": {"at_report": [{"100": {"message": "Transient object was inserted.", "objname": "2026ahcq"}}]}},
}


def falso_post(respostas):
    chamadas = []

    def post(url, campos, cfg):
        chamadas.append(url)
        return respostas[min(len(chamadas), len(respostas)) - 1]

    return post, chamadas


class TesteEnvio(unittest.TestCase):
    def test_aceito_devolve_nome(self):
        post, chamadas = falso_post([{"id_code": 200, "data": {"report_id": 7}}, {"id_code": 404}, ACEITA])
        r = envio.enviar({"at_report": {}}, CFG, post=post, dormir=lambda s: None)
        self.assertTrue(r["ok"])
        self.assertEqual((r["nome"], r["report_id"]), ("2026ahcq", 7))
        self.assertTrue(chamadas[0].startswith(envio.PRODUCAO + "/set/bulk-report"))

    def test_recusado_mostra_o_motivo(self):
        post, _ = falso_post([{"id_code": 200, "data": {"report_id": 8}}, RECUSA])
        r = envio.enviar({}, CFG, post=post, dormir=lambda s: None)
        self.assertFalse(r["ok"])
        self.assertEqual(r["erros"], ["at_report.reporting_groupid: Invalid. DebugNum-134"])

    def test_sandbox_usa_outro_endereco(self):
        post, chamadas = falso_post([{"id_code": 400, "id_message": "Bad request"}])
        r = envio.enviar({}, CFG, sandbox=True, post=post, dormir=lambda s: None)
        self.assertFalse(r["ok"])
        self.assertTrue(chamadas[0].startswith(envio.SANDBOX))


if __name__ == "__main__":
    unittest.main()
