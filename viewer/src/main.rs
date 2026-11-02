//! CacaSN Viewer: mostra um aviso do CacaSN (objeto TNS, ZTF, classificação).
//! Uso: cacasn-viewer <titulo> <texto> [link]
use eframe::egui;
use regex::Regex;

struct Aviso {
    titulo: String,
    texto: String,
    link: Option<String>,
    tns: Option<String>,
    ztf: Vec<String>,
    tipo: Option<String>,
}

impl Aviso {
    fn novo(titulo: String, texto: String, link: Option<String>) -> Self {
        let tns = Regex::new(r"\b(?:SN|AT)\s?(\d{4}[a-z]{1,4})\b").unwrap()
            .captures(&texto).map(|c| c[1].to_string());
        let ztf = Regex::new(r"\bZTF\d{2}[a-z]{7}\b").unwrap()
            .find_iter(&texto).map(|m| m.as_str().to_string()).collect();
        let tipo = Regex::new(r"=\s*(SN\s?[A-Za-z0-9\-]+|TDE|AGN|CV|Nova|LBV)").unwrap()
            .captures(&texto).map(|c| c[1].to_string());
        Self { titulo, texto, link, tns, ztf, tipo }
    }
}

fn linha(ui: &mut egui::Ui, rotulo: &str, valor: &str) {
    ui.label(egui::RichText::new(rotulo).weak());
    ui.label(egui::RichText::new(valor).strong().monospace());
    ui.end_row();
}

impl eframe::App for Aviso {
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading(&self.titulo);
            ui.add_space(6.0);
            ui.label(&self.texto);
            ui.separator();
            egui::Grid::new("dados").num_columns(2).spacing([16.0, 8.0]).show(ui, |ui| {
                linha(ui, "Objeto TNS", self.tns.as_deref().map(|t| format!("{t}")).as_deref().unwrap_or("—"));
                linha(ui, "Classificação", self.tipo.as_deref().unwrap_or("—"));
                linha(ui, "ZTF", &if self.ztf.is_empty() { "—".into() } else { self.ztf.join(", ") });
            });
            ui.separator();
            ui.horizontal_wrapped(|ui| {
                if let Some(t) = &self.tns {
                    if ui.button("Abrir no TNS").clicked() {
                        let _ = open::that(format!("https://www.wis-tns.org/object/{t}"));
                    }
                }
                for z in &self.ztf {
                    if ui.button(format!("{z} no ALeRCE")).clicked() {
                        let _ = open::that(format!("https://alerce.online/object/{z}"));
                    }
                }
                if let Some(l) = &self.link {
                    if ui.button("Abrir link do aviso").clicked() {
                        let _ = open::that(l);
                    }
                }
            });
        });
    }
}

fn main() -> eframe::Result {
    let mut a = std::env::args().skip(1);
    let titulo = a.next().unwrap_or_else(|| "CacaSN".into());
    let texto = a.next().unwrap_or_else(|| "Nenhum aviso recebido.".into());
    let link = a.next();
    let opcoes = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([520.0, 300.0]).with_title("CacaSN"),
        ..Default::default()
    };
    eframe::run_native("CacaSN", opcoes, Box::new(move |_| Ok(Box::new(Aviso::novo(titulo, texto, link)))))
}

#[cfg(test)]
mod testes {
    use super::*;
    #[test]
    fn extrai_dados_do_aviso() {
        let a = Aviso::novo("t".into(), "SN 2026aexm = SN Ia: o CacaSN tinha visto (ZTF26acaznbf)".into(), None);
        assert_eq!(a.tns.as_deref(), Some("2026aexm"));
        assert_eq!(a.tipo.as_deref(), Some("SN Ia"));
        assert_eq!(a.ztf, vec!["ZTF26acaznbf"]);
    }
}
