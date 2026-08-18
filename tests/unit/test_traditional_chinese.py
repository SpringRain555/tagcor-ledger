"""守門：專案的中文一律是繁體，不得混入簡體字。

字表只收「簡體專用」字 —— 繁簡同形的字不列入，否則會誤報。

2026-08-18 加入時對全專案實跑過，移除五個誤報：`量`、`常`、`伙`、`抽`、`骨`。
同日再對 `D:\\Projects\\_meta` 與 `D:\\Obsidian\\Certs` 共 204 個繁體 Markdown 實跑，
又移除三個：`承`（繼承／继承同形）、`殖`（繁殖）、`璃`（玻璃）。以上八個字在繁簡是
同一個碼位，收進來只會誤報。

**日後要加字進來，先拿一批真的繁體文章跑一次確認沒有新誤報** —— 一個會對正常寫作
報錯的守門，比沒有守門更糟，因為你會學會忽略它。

已知的一個邊界：`温`（U+6E29）留在表內，因為台灣標準字形是 `溫`（U+6EAB）。但
`温` 也是姓氏的通行異體，若日後要寫到用這個字形的人名，是把該字從表裡拿掉、而不是
去改人家的名字。
"""

from __future__ import annotations

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SKIP_DIRS = {
    ".git",
    "__pycache__",
    "archive",  # docs/archive 是歷史文件，不再維護
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
}

SCANNED_SUFFIXES = {".md", ".py", ".json", ".ps1", ".toml", ".yaml", ".yml", ".qss"}

SIMPLIFIED_ONLY = set(
    "个们为这说关边现时从会单实义检测计认证记录数据库备简体转换类项资设误处"
    "态运长维护读权规则图网页显输选择确删执开启动结载储术语该问题决议论觉变"
    "编码译释标准级联统划组织优势复杂难参传递归环继属调返异错试盖"
    "断与并无万专业东丝丢严丰临举乐习乡书买乱争亏云亚产亲亿仅仑仓仪价众伟"
    "伤伦伪余佣侠侣侦侧俭债倾偿儿兑兰兴兹养兽内冈册军农冯冲况冻净凉减凑几凤"
    "凭凯击凿刍刘刚创别刹剂剑剥劝办务动励劲劳勋医华协卖卫却厂厅历厉压厌厢厦"
    "厨县双发变叙叠号叹吁吓吕吗吨听吴呐员响哑哗唤啧啬喷园围国圆圣场坏块坚坛"
    "坝坞坟垄垒垦垫墙壮壳壶够头夸夹夺奋奖奥妆妇妈娄娱孙学宁宝宠审宪宫宽宾寝"
    "对寻导寿将尔尘尝尧层屉届属屡屿岁岂岗岛岭峡崭巩币帅师帐帘帜带帧帮广庄庆"
    "庐庙庞废异弃张弥弯弹强归当录彻径忆忧怀总恋恒恳恼悦悬惊惧惨惭惯愤愿懒战"
    "户扑扩扫扬扰抚抛护报担拟拢拣拥拦拧拨挂挚挡挤挥损捡换搁搂搅携摄摆摇摊撑"
    "敌敛斋斗斩旧旷显晋晒晓晕暂机杀权条来杨杰极构枢标栈栋树桥档梦棂楼横欢欧"
    "毁气汇汉沟没泞泪浅浆浇济浏浑浓涛润涨渐温湾湿满滤滥灭灯灵灾炉点炼烟烦"
    "烧热爱爷牵状犹独狮献玛环玺现瑶电画畅疗疯痴皱盏盐监盗盘着睁矫矿码砖础"
    "确碍礼祸禄离积称稳穷窃窑窜窝竖竞笔筑筛签箩篮籁粮紧纠红纪纯纲纳纵纷纸纹"
    "线练组细织终绍经绑结绕给绝统绩续绪绳维绵综绿缀缓缔编缘缚缝缩缴网罗罚罢"
    "羁翘耻聂职联聪肃肠肤肾肿胁胆胜脉脏脑脚脱腊腾舰舱艰艳节芦苏苹茧荐荡荣药"
    "莱莲获营萧萨蓝虏虑虚虫虽虾蚁蛮衅补衬装见观规觅视览觉触誉计订认讥讨让训"
    "议讯记讲讳讶许论设访诀证评识诈诉词译试诗诚话诞询该详诫语误诱说诵请诸读"
    "课调谅谈谋谎谐谓谢谣谱贝贞负贡财责贤败账货质贩贪贫贬购贮贯贱贴贵贷贸费"
    "贺贼贾赁资赋赌赏赐赔赖赘赚赛赞赠赢赣赵赶趋跃践跷踪蹒躯车轧轨轩转轮软轰"
    "轴轻载轿较辅辆辈辉辑输辖辗辙辞辩边辽达迁过迈还进远违连迟适逊递逻遗邓邮"
    "郑释鉴针钉钓钟钢钥钱钻铁铃铅铜铝银铸铺链销锁锅锈锐错锦键锯镇镜长门闪"
    "闭问闯闲间闷闻阀阁阅阐队阳阴阵阶际陆陈险随隐隶难雏雾霉静韦韩韵页顶顷项"
    "顺须顽顾顿颁预领颈频颗题颜额颠风飘飞饥饭饮饰饱饲饶饼饿馆馈马驭驮驰驱驳"
    "驴驶驻驾验骄骆骗骤髅魇鱼鲁鲜鸟鸡鸣鸭鸿鹅鹏鹤麦黄齐齿龄龙龟"
)


SELF = Path(__file__).resolve()


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(PROJECT_ROOT).parts):
            continue
        # 這個檔案本身就是簡體字表，掃自己一定會中。
        if path.resolve() == SELF:
            continue
        files.append(path)
    return files


def test_scanner_detects_known_simplified_text() -> None:
    """陽性對照：字表若壞掉，這個測試會先失敗，而不是讓掃描靜默通過。"""
    assert {ch for ch in "重构产品知识结构" if ch in SIMPLIFIED_ONLY} == {"构", "产", "识", "结"}
    assert not {ch for ch in "重構產品知識結構餘額盤點" if ch in SIMPLIFIED_ONLY}


def test_no_simplified_chinese_in_project() -> None:
    offenders: list[str] = []
    for path in _scanned_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(lines, 1):
            found = sorted({ch for ch in line if ch in SIMPLIFIED_ONLY})
            if found:
                relative = path.relative_to(PROJECT_ROOT)
                offenders.append(f"{relative}:{number} 出現 {''.join(found)} -> {line.strip()[:80]}")

    if offenders:
        pytest.fail("偵測到簡體字：\n" + "\n".join(offenders))


def test_scan_actually_covers_files() -> None:
    """避免 SKIP_DIRS 或副檔名清單寫錯導致什麼都沒掃到。"""
    files = _scanned_files()
    assert len(files) > 30
    names = {path.name for path in files}
    assert "AGENTS.md" in names
    assert "README.md" in names
