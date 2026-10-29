"""Portuguese stopwords for the BM25 tokenizer.

Function words (articles, prepositions, pronouns, auxiliary verb forms) appear in
almost every post, so they only add noise to keyword matching. The list is written
without accents because the tokenizer strips accents before comparing ("é" -> "e",
"está" -> "esta", "não" -> "nao").
"""

# A whitespace-separated block is far easier to read and extend than a list literal
# with hundreds of quoted words.
_STOPWORDS_TEXT = """
a ao aos as o os um uma uns umas
de do da dos das em no na nos nas num numa nuns numas
por pelo pela pelos pelas para pra pro pras pros com sem sob sobre
ate contra entre apos desde perante
e ou mas nem que se porque pois como quando onde enquanto entao assim
tambem ainda ja so mais menos muito muita muitos muitas pouco pouca tao tanto
tanta tantos tantas bem
eu tu ele ela nos vos eles elas voce voces me te lhe lhes mim ti
meu meus minha minhas teu teus tua tuas seu seus sua suas nosso nossos nossa nossas
dele dela deles delas
este esta estes estas esse essa esses essas aquele aquela aqueles aquelas
isto isso aquilo deste desta destes destas desse dessa desses dessas disto disso
neste nesta nestes nestas nesse nessa nesses nessas nisto nisso
daquele daquela daquilo naquele naquela naquilo
qual quais quem quanto quantos quanta quantas cujo cuja cujos cujas
todo toda todos todas outro outra outros outras algum alguma alguns algumas
nenhum nenhuma qualquer quaisquer cada tal tais mesmo mesma mesmos mesmas
aqui ali la ca sim nao
ser sou es somos sao era eras eramos eram fui foi fomos foram sera serao
seria seriam seja sejam fosse fossem for forem sendo sido
estar estou estamos estao estava estavam esteve estiveram estando estado
ter tenho tem temos tinha tinham teve tiveram tendo tido tiver tiverem
ha haver havia houve
vai vao vou ir
"""

STOPWORDS_PT: frozenset[str] = frozenset(_STOPWORDS_TEXT.split())
