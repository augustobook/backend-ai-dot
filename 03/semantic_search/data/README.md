# Dataset

100 real health articles from the **Portuguese Wikipedia**
([pt.wikipedia.org](https://pt.wikipedia.org)), written in Portuguese, used as the
document collection of the semantic search demo.

## License and attribution

- **Authors:** Colaboradores da Wikipédia (the full history of each article is linked
  from its page).
- **License:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.pt-br). The texts in `documents/` are distributed
  under the same license.
- **Changes:** the plain text of each article was extracted through the MediaWiki API;
  reference-only sections (references, external links, "see also"...) and editorial
  markers such as `[carece de fontes]` were removed; articles longer than
  2000 words were cut at a section boundary. The `adapted` field of each file
  says which changes apply to it.
- **Disclaimer:** encyclopedic content, used only to demonstrate information retrieval.
  It is not medical advice.

The source URL, the revision id and the retrieval date of every article are stored in
its front matter, so the exact original text can be checked.

## Reproducing

```bash
uv run python scripts/fetch_dataset.py          # download every article again
uv run python scripts/fetch_dataset.py chr-02   # only some ids
```

The articles keep changing on Wikipedia; a new download may produce slightly different
texts (and a different dataset hash, which makes the ingestion rebuild the index).

## Categories

| Category | Documents |
|---|---|
| Nutrição | 20 |
| Saúde mental | 20 |
| Sono e atividade física | 20 |
| Doenças crônicas | 20 |
| Doenças infecciosas e prevenção | 20 |

## Documents

| ID | Category | Article | Revision | Retrieved | Words |
|---|---|---|---|---|---|
| `act-01` | Sono e atividade física | [Sono](https://pt.wikipedia.org/wiki/Sono) | 72356125 | 2026-10-29 | 1821 |
| `act-02` | Sono e atividade física | [Insônia](https://pt.wikipedia.org/wiki/Ins%C3%B4nia) | 71371928 | 2026-10-29 | 1916 |
| `act-03` | Sono e atividade física | [Apneia do sono](https://pt.wikipedia.org/wiki/Apneia_do_sono) | 72995630 | 2026-10-29 | 1736 |
| `act-04` | Sono e atividade física | [Ritmo circadiano](https://pt.wikipedia.org/wiki/Ritmo_circadiano) | 73125187 | 2026-10-29 | 1200 |
| `act-05` | Sono e atividade física | [Jet lag](https://pt.wikipedia.org/wiki/Jet_lag) | 70495142 | 2026-10-29 | 503 |
| `act-06` | Sono e atividade física | [Exercício físico](https://pt.wikipedia.org/wiki/Exerc%C3%ADcio_f%C3%ADsico) | 72485294 | 2026-10-29 | 1231 |
| `act-07` | Sono e atividade física | [Musculação](https://pt.wikipedia.org/wiki/Muscula%C3%A7%C3%A3o) | 72351514 | 2026-10-29 | 1942 |
| `act-08` | Sono e atividade física | [Corrida](https://pt.wikipedia.org/wiki/Corrida) | 71274826 | 2026-10-29 | 917 |
| `act-09` | Sono e atividade física | [Alongamento](https://pt.wikipedia.org/wiki/Alongamento) | 70780687 | 2026-10-29 | 707 |
| `act-10` | Sono e atividade física | [Sedentarismo](https://pt.wikipedia.org/wiki/Sedentarismo) | 73158521 | 2026-10-29 | 866 |
| `act-11` | Sono e atividade física | [Higiene do sono](https://pt.wikipedia.org/wiki/Higiene_do_sono) | 69725233 | 2026-10-29 | 1962 |
| `act-12` | Sono e atividade física | [Privação de sono](https://pt.wikipedia.org/wiki/Priva%C3%A7%C3%A3o_de_sono) | 73250457 | 2026-10-29 | 752 |
| `act-13` | Sono e atividade física | [Narcolepsia](https://pt.wikipedia.org/wiki/Narcolepsia) | 68404580 | 2026-10-29 | 388 |
| `act-14` | Sono e atividade física | [Sonambulismo](https://pt.wikipedia.org/wiki/Sonambulismo) | 73198350 | 2026-10-29 | 1069 |
| `act-15` | Sono e atividade física | [Síndrome das pernas inquietas](https://pt.wikipedia.org/wiki/S%C3%ADndrome_das_pernas_inquietas) | 70224219 | 2026-10-29 | 892 |
| `act-16` | Sono e atividade física | [Bruxismo](https://pt.wikipedia.org/wiki/Bruxismo) | 72288458 | 2026-10-29 | 1730 |
| `act-17` | Sono e atividade física | [Melatonina](https://pt.wikipedia.org/wiki/Melatonina) | 72956473 | 2026-10-29 | 1479 |
| `act-18` | Sono e atividade física | [Ioga](https://pt.wikipedia.org/wiki/Ioga) | 70938304 | 2026-10-29 | 1939 |
| `act-19` | Sono e atividade física | [Pilates](https://pt.wikipedia.org/wiki/Pilates) | 73240732 | 2026-10-29 | 744 |
| `act-20` | Sono e atividade física | [Natação](https://pt.wikipedia.org/wiki/Nata%C3%A7%C3%A3o) | 69819457 | 2026-10-29 | 573 |
| `chr-01` | Doenças crônicas | [Hipertensão arterial](https://pt.wikipedia.org/wiki/Hipertens%C3%A3o_arterial) | 67194124 | 2026-10-29 | 1718 |
| `chr-02` | Doenças crônicas | [Diabetes mellitus](https://pt.wikipedia.org/wiki/Diabetes_mellitus) | 71153767 | 2026-10-29 | 1886 |
| `chr-03` | Doenças crônicas | [Colesterol](https://pt.wikipedia.org/wiki/Colesterol) | 73148235 | 2026-10-29 | 1617 |
| `chr-04` | Doenças crônicas | [Acidente vascular cerebral](https://pt.wikipedia.org/wiki/Acidente_vascular_cerebral) | 72721400 | 2026-10-29 | 1998 |
| `chr-05` | Doenças crônicas | [Enfarte agudo do miocárdio](https://pt.wikipedia.org/wiki/Enfarte_agudo_do_mioc%C3%A1rdio) | 71463561 | 2026-10-29 | 1887 |
| `chr-06` | Doenças crônicas | [Asma](https://pt.wikipedia.org/wiki/Asma) | 72816543 | 2026-10-29 | 1825 |
| `chr-07` | Doenças crônicas | [Doença pulmonar obstrutiva crónica](https://pt.wikipedia.org/wiki/Doen%C3%A7a_pulmonar_obstrutiva_cr%C3%B3nica) | 72728479 | 2026-10-29 | 1997 |
| `chr-08` | Doenças crônicas | [Osteoporose](https://pt.wikipedia.org/wiki/Osteoporose) | 72843038 | 2026-10-29 | 1775 |
| `chr-09` | Doenças crônicas | [Cancro da mama](https://pt.wikipedia.org/wiki/Cancro_da_mama) | 73215113 | 2026-10-29 | 1967 |
| `chr-10` | Doenças crônicas | [Doença renal crônica](https://pt.wikipedia.org/wiki/Doen%C3%A7a_renal_cr%C3%B4nica) | 68676207 | 2026-10-29 | 1742 |
| `chr-11` | Doenças crônicas | [Artrite reumatoide](https://pt.wikipedia.org/wiki/Artrite_reumatoide) | 70129165 | 2026-10-29 | 1319 |
| `chr-12` | Doenças crônicas | [Artrose](https://pt.wikipedia.org/wiki/Artrose) | 71520343 | 2026-10-29 | 1620 |
| `chr-13` | Doenças crônicas | [Doença de Alzheimer](https://pt.wikipedia.org/wiki/Doen%C3%A7a_de_Alzheimer) | 72748095 | 2026-10-29 | 1913 |
| `chr-14` | Doenças crônicas | [Doença de Parkinson](https://pt.wikipedia.org/wiki/Doen%C3%A7a_de_Parkinson) | 73222475 | 2026-10-29 | 1932 |
| `chr-15` | Doenças crônicas | [Enxaqueca](https://pt.wikipedia.org/wiki/Enxaqueca) | 72472024 | 2026-10-29 | 1975 |
| `chr-16` | Doenças crônicas | [Hipotiroidismo](https://pt.wikipedia.org/wiki/Hipotiroidismo) | 66611972 | 2026-10-29 | 374 |
| `chr-17` | Doenças crônicas | [Insuficiência cardíaca](https://pt.wikipedia.org/wiki/Insufici%C3%AAncia_card%C3%ADaca) | 71573868 | 2026-10-29 | 1852 |
| `chr-18` | Doenças crônicas | [Gota (doença)](https://pt.wikipedia.org/wiki/Gota_(doen%C3%A7a)) | 68658186 | 2026-10-29 | 971 |
| `chr-19` | Doenças crônicas | [Fibromialgia](https://pt.wikipedia.org/wiki/Fibromialgia) | 73236809 | 2026-10-29 | 1947 |
| `chr-20` | Doenças crônicas | [Lúpus eritematoso disseminado](https://pt.wikipedia.org/wiki/L%C3%BApus_eritematoso_disseminado) | 71413783 | 2026-10-29 | 1825 |
| `inf-01` | Doenças infecciosas e prevenção | [Dengue](https://pt.wikipedia.org/wiki/Dengue) | 69233950 | 2026-10-29 | 1803 |
| `inf-02` | Doenças infecciosas e prevenção | [Gripe](https://pt.wikipedia.org/wiki/Gripe) | 72328603 | 2026-10-29 | 1661 |
| `inf-03` | Doenças infecciosas e prevenção | [COVID-19](https://pt.wikipedia.org/wiki/COVID-19) | 73272525 | 2026-10-29 | 1967 |
| `inf-04` | Doenças infecciosas e prevenção | [Sarampo](https://pt.wikipedia.org/wiki/Sarampo) | 73004649 | 2026-10-29 | 1950 |
| `inf-05` | Doenças infecciosas e prevenção | [Tuberculose](https://pt.wikipedia.org/wiki/Tuberculose) | 73307479 | 2026-10-29 | 1966 |
| `inf-06` | Doenças infecciosas e prevenção | [Vacina](https://pt.wikipedia.org/wiki/Vacina) | 72262664 | 2026-10-29 | 1967 |
| `inf-07` | Doenças infecciosas e prevenção | [Antibiótico](https://pt.wikipedia.org/wiki/Antibi%C3%B3tico) | 73065605 | 2026-10-29 | 1982 |
| `inf-08` | Doenças infecciosas e prevenção | [Resistência antibiótica](https://pt.wikipedia.org/wiki/Resist%C3%AAncia_antibi%C3%B3tica) | 73113237 | 2026-10-29 | 1418 |
| `inf-09` | Doenças infecciosas e prevenção | [Febre amarela](https://pt.wikipedia.org/wiki/Febre_amarela) | 72961270 | 2026-10-29 | 1811 |
| `inf-10` | Doenças infecciosas e prevenção | [Lavagem das mãos](https://pt.wikipedia.org/wiki/Lavagem_das_m%C3%A3os) | 66543307 | 2026-10-29 | 304 |
| `inf-11` | Doenças infecciosas e prevenção | [Síndrome da imunodeficiência adquirida](https://pt.wikipedia.org/wiki/S%C3%ADndrome_da_imunodefici%C3%AAncia_adquirida) | 73221962 | 2026-10-29 | 1864 |
| `inf-12` | Doenças infecciosas e prevenção | [Hepatite B](https://pt.wikipedia.org/wiki/Hepatite_B) | 71308312 | 2026-10-29 | 1701 |
| `inf-13` | Doenças infecciosas e prevenção | [Malária](https://pt.wikipedia.org/wiki/Mal%C3%A1ria) | 73004621 | 2026-10-29 | 1663 |
| `inf-14` | Doenças infecciosas e prevenção | [Febre zika](https://pt.wikipedia.org/wiki/Febre_zika) | 72750103 | 2026-10-29 | 1876 |
| `inf-15` | Doenças infecciosas e prevenção | [Chicungunha](https://pt.wikipedia.org/wiki/Chicungunha) | 72833500 | 2026-10-29 | 1325 |
| `inf-16` | Doenças infecciosas e prevenção | [Meningite](https://pt.wikipedia.org/wiki/Meningite) | 71009656 | 2026-10-29 | 1953 |
| `inf-17` | Doenças infecciosas e prevenção | [Pneumonia](https://pt.wikipedia.org/wiki/Pneumonia) | 73056017 | 2026-10-29 | 1859 |
| `inf-18` | Doenças infecciosas e prevenção | [Infecção do trato urinário](https://pt.wikipedia.org/wiki/Infec%C3%A7%C3%A3o_do_trato_urin%C3%A1rio) | 71181449 | 2026-10-29 | 1645 |
| `inf-19` | Doenças infecciosas e prevenção | [Herpes zoster](https://pt.wikipedia.org/wiki/Herpes_zoster) | 67574648 | 2026-10-29 | 1722 |
| `inf-20` | Doenças infecciosas e prevenção | [Varicela](https://pt.wikipedia.org/wiki/Varicela) | 71154939 | 2026-10-29 | 1720 |
| `men-01` | Saúde mental | [Ansiedade](https://pt.wikipedia.org/wiki/Ansiedade) | 71648976 | 2026-10-29 | 1186 |
| `men-02` | Saúde mental | [Transtorno depressivo maior](https://pt.wikipedia.org/wiki/Transtorno_depressivo_maior) | 72946517 | 2026-10-29 | 1894 |
| `men-03` | Saúde mental | [Transtorno de ansiedade generalizada](https://pt.wikipedia.org/wiki/Transtorno_de_ansiedade_generalizada) | 73299725 | 2026-10-29 | 1145 |
| `men-04` | Saúde mental | [Síndrome de burnout](https://pt.wikipedia.org/wiki/S%C3%ADndrome_de_burnout) | 73222069 | 2026-10-29 | 1798 |
| `men-05` | Saúde mental | [Estresse](https://pt.wikipedia.org/wiki/Estresse) | 71077668 | 2026-10-29 | 1964 |
| `men-06` | Saúde mental | [Meditação](https://pt.wikipedia.org/wiki/Medita%C3%A7%C3%A3o) | 71261698 | 2026-10-29 | 1413 |
| `men-07` | Saúde mental | [Atenção plena](https://pt.wikipedia.org/wiki/Aten%C3%A7%C3%A3o_plena) | 71220466 | 2026-10-29 | 1993 |
| `men-08` | Saúde mental | [Transtorno de pânico](https://pt.wikipedia.org/wiki/Transtorno_de_p%C3%A2nico) | 73299818 | 2026-10-29 | 1791 |
| `men-09` | Saúde mental | [Transtorno do déficit de atenção e hiperatividade](https://pt.wikipedia.org/wiki/Transtorno_do_d%C3%A9ficit_de_aten%C3%A7%C3%A3o_e_hiperatividade) | 73299857 | 2026-10-29 | 1211 |
| `men-10` | Saúde mental | [Transtorno bipolar](https://pt.wikipedia.org/wiki/Transtorno_bipolar) | 72960598 | 2026-10-29 | 1982 |
| `men-11` | Saúde mental | [Transtorno obsessivo-compulsivo](https://pt.wikipedia.org/wiki/Transtorno_obsessivo-compulsivo) | 73170348 | 2026-10-29 | 1908 |
| `men-12` | Saúde mental | [Transtorno de estresse pós-traumático](https://pt.wikipedia.org/wiki/Transtorno_de_estresse_p%C3%B3s-traum%C3%A1tico) | 73299756 | 2026-10-29 | 1980 |
| `men-13` | Saúde mental | [Esquizofrenia](https://pt.wikipedia.org/wiki/Esquizofrenia) | 72601162 | 2026-10-29 | 1960 |
| `men-14` | Saúde mental | [Transtorno do espectro autista](https://pt.wikipedia.org/wiki/Transtorno_do_espectro_autista) | 73299898 | 2026-10-29 | 1982 |
| `men-15` | Saúde mental | [Alcoolismo](https://pt.wikipedia.org/wiki/Alcoolismo) | 71748825 | 2026-10-29 | 1808 |
| `men-16` | Saúde mental | [Anorexia nervosa](https://pt.wikipedia.org/wiki/Anorexia_nervosa) | 72208303 | 2026-10-29 | 1931 |
| `men-17` | Saúde mental | [Bulimia nervosa](https://pt.wikipedia.org/wiki/Bulimia_nervosa) | 71052112 | 2026-10-29 | 1284 |
| `men-18` | Saúde mental | [Transtorno de ansiedade social](https://pt.wikipedia.org/wiki/Transtorno_de_ansiedade_social) | 73287546 | 2026-10-29 | 887 |
| `men-19` | Saúde mental | [Psicoterapia](https://pt.wikipedia.org/wiki/Psicoterapia) | 70759691 | 2026-10-29 | 1785 |
| `men-20` | Saúde mental | [Terapia cognitivo-comportamental](https://pt.wikipedia.org/wiki/Terapia_cognitivo-comportamental) | 73244713 | 2026-10-29 | 1694 |
| `nut-01` | Nutrição | [Nutrição](https://pt.wikipedia.org/wiki/Nutri%C3%A7%C3%A3o) | 72573457 | 2026-10-29 | 490 |
| `nut-02` | Nutrição | [Obesidade](https://pt.wikipedia.org/wiki/Obesidade) | 72995106 | 2026-10-29 | 1871 |
| `nut-03` | Nutrição | [Desidratação](https://pt.wikipedia.org/wiki/Desidrata%C3%A7%C3%A3o) | 71722579 | 2026-10-29 | 1689 |
| `nut-04` | Nutrição | [Fibra dietética](https://pt.wikipedia.org/wiki/Fibra_diet%C3%A9tica) | 72408659 | 2026-10-29 | 1350 |
| `nut-05` | Nutrição | [Vitamina D](https://pt.wikipedia.org/wiki/Vitamina_D) | 72850599 | 2026-10-29 | 1973 |
| `nut-06` | Nutrição | [Dieta mediterrânica](https://pt.wikipedia.org/wiki/Dieta_mediterr%C3%A2nica) | 69673696 | 2026-10-29 | 1392 |
| `nut-07` | Nutrição | [Vegetarianismo](https://pt.wikipedia.org/wiki/Vegetarianismo) | 72811445 | 2026-10-29 | 1857 |
| `nut-08` | Nutrição | [Anemia por deficiência de ferro](https://pt.wikipedia.org/wiki/Anemia_por_defici%C3%AAncia_de_ferro) | 71248328 | 2026-10-29 | 1202 |
| `nut-09` | Nutrição | [Desnutrição](https://pt.wikipedia.org/wiki/Desnutri%C3%A7%C3%A3o) | 70873477 | 2026-10-29 | 746 |
| `nut-10` | Nutrição | [Sódio](https://pt.wikipedia.org/wiki/S%C3%B3dio) | 72381979 | 2026-10-29 | 827 |
| `nut-11` | Nutrição | [Obstipação](https://pt.wikipedia.org/wiki/Obstipa%C3%A7%C3%A3o) | 68306136 | 2026-10-29 | 429 |
| `nut-12` | Nutrição | [Diarreia](https://pt.wikipedia.org/wiki/Diarreia) | 69722885 | 2026-10-29 | 1862 |
| `nut-13` | Nutrição | [Intolerância à lactose](https://pt.wikipedia.org/wiki/Intoler%C3%A2ncia_%C3%A0_lactose) | 72740738 | 2026-10-29 | 1233 |
| `nut-14` | Nutrição | [Doença celíaca](https://pt.wikipedia.org/wiki/Doen%C3%A7a_cel%C3%ADaca) | 72472915 | 2026-10-29 | 1922 |
| `nut-15` | Nutrição | [Probiótico](https://pt.wikipedia.org/wiki/Probi%C3%B3tico) | 73033279 | 2026-10-29 | 1045 |
| `nut-16` | Nutrição | [Vitamina C](https://pt.wikipedia.org/wiki/Vitamina_C) | 70149564 | 2026-10-29 | 475 |
| `nut-17` | Nutrição | [Vitamina B12](https://pt.wikipedia.org/wiki/Vitamina_B12) | 71108442 | 2026-10-29 | 1405 |
| `nut-18` | Nutrição | [Ômega 3](https://pt.wikipedia.org/wiki/%C3%94mega_3) | 67386007 | 2026-10-29 | 447 |
| `nut-19` | Nutrição | [Doença de refluxo gastroesofágico](https://pt.wikipedia.org/wiki/Doen%C3%A7a_de_refluxo_gastroesof%C3%A1gico) | 73143876 | 2026-10-29 | 1241 |
| `nut-20` | Nutrição | [Gastrite](https://pt.wikipedia.org/wiki/Gastrite) | 71266417 | 2026-10-29 | 1409 |
