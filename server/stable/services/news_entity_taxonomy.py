"""新闻实体分类规范；纯数据，不触发赛马库查询或修改生产配置。"""
LEGACY_TYPES = frozenset({'horse', 'person', 'race', 'organization', 'place', 'common_word'})
RACING_TYPES = LEGACY_TYPES | {'race_related', 'racing_honor', 'auction', 'umamusume'}
CONTEXT_CONTRACTS = frozenset({'context-v2', 'context-v3'})
TAXONOMY_VERSION = 'racing-v1'
ENTITY_RULES = {
    'horse': '赛马、退役马、繁殖马、马术用马、诱导马及有赛马血统关系的具名马匹。',
    'person': '具体人物及上下文明确的姓名简称；获胜者不一定是马，骑师仍为person。',
    'race': '单场赛马、马术、马球赛事；相邻正式冠名连同括号保持原文，日期地点不吞入名称。',
    'organization': '机构及明确经营团队；按具体语境与品牌/场地区分。',
    'place': '具名地点、场馆、区域及语境明确的简称；普通设施称呼不标。',
    'race_related': '具名比赛日、系列赛、赛事节、阶段、赛事周/期以及奖金奖励计划。',
    'racing_honor': '赛马直接相关的冠军称号、奖项、荣誉名录、排名体系及简称。',
    'auction': '赛马拍卖活动及有明确指称的简称。',
    'umamusume': '与赛马娘Pretty Derby企划直接强相关且不属于其他类的专名。',
}
EXCLUSION_RULES = (
    '排除品牌/平台产品、节目、展览、画作、灾害、产品型号、语言名称、来源栏目/部门、'
    '非赛事线下活动、家族/马族/后代群体；umamusume是企划专名特例。'
    '排除競馬学校/騎手養成所等非重要专名的泛称。'
    '品牌在原文明确指公司时可为organization；不能仅因获奖者是骑师而纳入无关社会奖项。'
    '排除普通类别如a Derby Trial、Cup horse，除非原文明示特定命名对象。'
    '未抽取的文本仍正常翻译，绝不删除。'
)


def entity_types(contract_version):
    if contract_version in {'legacy', 'context-v2'}:
        return LEGACY_TYPES
    if contract_version in {'context-v3', 'racing-spans-v1'}:
        return RACING_TYPES
    raise ValueError('unknown_entity_contract')


def unit_contract(contract_version):
    if contract_version not in CONTEXT_CONTRACTS:
        raise ValueError('unknown_entity_contract')
    return 'entity-units-v3' if contract_version == 'context-v3' else 'entity-units-v2'


def context_from_unit(version):
    versions = {'entity-units-v2': 'context-v2', 'entity-units-v3': 'context-v3'}
    if version not in versions:
        raise ValueError('unknown_entity_contract')
    return versions[version]


def entity_limit(contract_version):
    entity_types(contract_version)
    return 256 if contract_version in {'context-v3', 'racing-spans-v1'} else 128
