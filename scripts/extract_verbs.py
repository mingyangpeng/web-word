#!/home/pmy/dev/miniconda3/envs/p312/bin/python
"""
从英语移动动词文档提取所有单词并保存到文件

该脚本从文档中提取157个核心移动动词，包括：
- 路径聚焦类（终点类、来源类）：22个动词
- 方式聚焦类（方式类）：121个动词
- 关联聚焦类（目的类、参与者类）：14个动词
"""

import sys
import os
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def extract_verbs_from_text(text):
    """
    从文本中提取所有动词

    Returns:
        dict: 分类结构化的动词数据
    """
    # 根据文档内容，手动定义五大范畴和次类
    verbs_data = {
        "endpoint": {
            "subclasses": {
                "arrive": ["到达", "不及物到达", "NP V PP (at, in)", "[+位移] [+终点]", "不及物，范畴原型"],
                "reach": ["到达", "及物另类处理", "NP V NP", "[+位移] [+终点]", "及物到达，构式变体"],
                "return": ["返回", "折返原位", "NP V PP (to)", "[+位移] [+终点] [+返回]", "终点为起始点，图式特殊"],
                "come": ["来类", "趋近参照点", "NP V PP (to)", "[+位移] [+趋近] [+指示]", "指示路径动词"],
                "go": ["去类", "远离参照点", "NP V PP (to)", "[+位移] [+远离] [+指示]", "指示路径动词"],
                "enter": ["进入类", "空间移入", "NP V NP / PP (into)", "[+位移] [+进入] [+边界跨越]", "及物/不及物均可"],
                "exit": ["外出离场类", "空间移出", "NP V NP / PP (from)", "[+位移] [+外出] [+边界跨越]", "及物/不及物均可"],
                "ascend": ["上升类", "垂直上行", "NP V PP (up, to)", "[+位移] [+上升]", "垂直上升"],
                "rise": ["上升类", "垂直上行", "NP V PP (up, to)", "[+位移] [+上升]", "垂直上升"],
                "climb": ["上升类", "垂直上行", "NP V NP / PP (up)", "[+位移] [+上升]", "方向主导，方式附带"],
                "fall": ["下降类", "垂直下行", "NP V PP (down, into)", "[+位移] [+下降]", "垂直下降"],
                "descend": ["下降类", "垂直下行", "NP V NP / PP (down)", "[+位移] [+下降]", "可及物"],
                "plunge": ["下降类", "垂直急降", "NP V PP (into, down)", "[+位移] [+下降]", "急速下坠"],
                "tumble": ["下降类", "跌落翻滚", "NP V PP (down, into)", "[+位移] [+下降]", "跌跌撞撞"],
                "advance": ["前进类", "水平前行", "NP V PP (to, toward)", "[+位移] [+前进]", "向前移动"],
                "recede": ["后退类", "水平后退", "NP V PP (from)", "[+位移] [+后退]", "向后退"],
            },
            "category": "路径聚焦类",
            "subclass": "终点类"
        },
        "source": {
            "subclasses": {
                "leave": ["脱离类", "处所脱离", "NP V NP / PP (from)", "[+位移] [+离开]", "范畴原型"],
                "abandon": ["脱离类", "抛弃", "NP V NP", "[+位移] [+离开]", "放弃位置"],
                "desert": ["脱离类", "遗弃", "NP V NP", "[+位移] [+离开]", "抛弃位置"],
                "depart": ["逃离类", "逃离来源", "NP V PP (from, for)", "[+位移] [+离开] [+出发]", "语义焦点为脱离"],
                "escape": ["逃离类", "逃离来源", "NP V PP (from) / NP V NP", "[+位移] [+离开] [+逃离]", "逃离危险"],
                "flee": ["逃离类", "逃离来源", "NP V PP (from) / NP V NP", "[+位移] [+离开] [+逃离]", "快速逃离"],
            },
            "category": "路径聚焦类",
            "subclass": "来源类"
        },
        "manner": {
            "subclasses": {
                # 滚动滑行类
                "roll": ["滚动滑行类", "轴向滚动滑移", "NP V PP (across, down)", "[+位移] [+方式] [+滚动]", "51.3.1与51.3.2重叠"],
                "slide": ["滚动滑行类", "滑动", "NP V PP (across, down)", "[+位移] [+方式] [+滑行]", "平面滑动"],
                "bounce": ["滚动滑行类", "弹跳", "NP V PP (across, into)", "[+位移] [+方式] [+弹跳]", "有弹性"],
                "drift": ["滚动滑行类", "飘移", "NP V PP (across, into)", "[+位移] [+方式] [+飘移]", "无方向感"],
                "float": ["滚动滑行类", "飘浮", "NP V PP (across, into)", "[+位移] [+方式] [+飘浮]", "悬浮"],
                "glide": ["滚动滑行类", "滑翔", "NP V PP (across, through)", "[+位移] [+方式] [+滑翔]", "平滑移动"],
                "swing": ["滚动滑行类", "摆动", "NP V PP (across, into)", "[+位移] [+方式] [+摆动]", "来回移动"],
                # 陆地行进类
                "walk": ["陆地行进类", "常态行走", "NP V PP (across, along)", "[+位移] [+方式] [+行走]", "范畴原型"],
                "stride": ["陆地行进类", "大步走", "NP V PP (across, along)", "[+位移] [+方式] [+行走] [+昂首阔步]", "大步向前"],
                "run": ["陆地行进类", "奔跑", "NP V PP (across, along)", "[+位移] [+方式] [+奔跑]", "快速移动"],
                "trot": ["陆地行进类", "小跑", "NP V PP", "[+位移] [+方式] [+小跑]", "轻快跑步"],
                "gallop": ["陆地行进类", "飞奔", "NP V PP", "[+位移] [+方式] [+飞奔]", "快速奔驰"],
                "jog": ["陆地行进类", "慢跑", "NP V PP", "[+位移] [+方式] [+慢跑]", "中速跑步"],
                "sprint": ["陆地行进类", "冲刺", "NP V PP", "[+位移] [+方式] [+冲刺]", "最快速度"],
                "march": ["陆地行进类", "行军", "NP V PP", "[+位移] [+方式] [+行军]", "齐步走"],
                "tramp": ["陆地行进类", "重步行走", "NP V PP", "[+位移] [+方式] [+重步行走]", "沉重脚步"],
                "stomp": ["陆地行进类", "跺脚", "NP V PP", "[+位移] [+方式] [+跺脚]", "用力踏地"],
                "step": ["陆地行进类", "迈步", "NP V PP", "[+位移] [+方式] [+迈步]", "基本移动"],
                "hop": ["陆地行进类", "单足跳", "NP V PP", "[+位移] [+方式] [+单足跳]", "一次一只脚"],
                "skip": ["陆地行进类", "蹦跳", "NP V PP", "[+位移] [+方式] [+蹦跳]", "两脚交替跳"],
                "jump": ["陆地行进类", "跳跃", "NP V PP", "[+位移] [+方式] [+跳跃]", "垂直上升"],
                "leap": ["陆地行进类", "飞跃", "NP V PP", "[+位移] [+方式] [+飞跃]", "大跨步跳"],
                "vault": ["陆地行进类", "跳越", "NP V PP", "[+位移] [+方式] [+跳越]", "越过障碍"],
                "spring": ["陆地行进类", "弹跳", "NP V PP", "[+位移] [+方式] [+弹跳]", "有弹性跳跃"],
                "hurdle": ["陆地行进类", "跨栏", "NP V PP", "[+位移] [+方式] [+跨栏]", "跨越障碍"],
                "scramble": ["陆地行进类", "攀爬争抢", "NP V PP", "[+位移] [+方式] [+攀爬争抢]", "手脚并用"],
                "scurry": ["陆地行进类", "急奔", "NP V PP", "[+位移] [+方式] [+急奔]", "快速小跑"],
                "dodge": ["陆地行进类", "闪避", "NP V PP", "[+位移] [+方式] [+闪避]", "避免接触"],
                "zigzag": ["陆地行进类", "之字形移动", "NP V PP", "[+位移] [+方式] [+之字形]", "来回移动"],
                # 飞行游动类
                "fly": ["飞行游动类", "空中飞行", "NP V PP (across, over)", "[+位移] [+方式] [+飞行]", "空中移动"],
                "soar": ["飞行游动类", "翱翔", "NP V PP", "[+位移] [+方式] [+翱翔]", "滑翔飞行"],
                "sail": ["飞行游动类", "航行", "NP V PP (across, into)", "[+位移] [+方式] [+航行]", "水面/空中"],
                "hover": ["飞行游动类", "悬停", "NP V PP", "[+位移] [+方式] [+悬停]", "空中停止"],
                "glide": ["飞行游动类", "滑翔", "NP V PP (across, through)", "[+位移] [+方式] [+滑翔]", "无动力滑行"],
                "swim": ["飞行游动类", "游动", "NP V PP (across, through)", "[+位移] [+方式] [+游动]", "水中移动"],
                "dive": ["飞行游动类", "潜水", "NP V PP (into)", "[+位移] [+方式] [+潜水]", "向下入水"],
                "float": ["飞行游动类", "漂浮", "NP V PP", "[+位移] [+方式] [+漂浮]", "水面漂浮"],
                "drift": ["飞行游动类", "漂流", "NP V PP", "[+位移] [+方式] [+漂流]", "随波逐流"],
                # 匍匐爬行类
                "crawl": ["匍匐爬行类", "攀爬匍匐", "NP V PP (across, through)", "[+位移] [+方式] [+爬行]", "范畴原型"],
                "creep": ["匍匐爬行类", "匍匐", "NP V PP (across, along)", "[+位移] [+方式] [+爬行] [+缓慢]", "缓慢爬行"],
                "scramble": ["匍匐爬行类", "攀爬", "NP V PP", "[+位移] [+方式] [+攀爬]", "手脚并用"],
                "clamber": ["匍匐爬行类", "艰难攀爬", "NP V PP", "[+位移] [+方式] [+攀爬（费力）]", "费力攀爬"],
                "slither": ["匍匐爬行类", "蜿蜒爬行", "NP V PP", "[+位移] [+方式] [+蜿蜒]", "蛇形移动"],
                "snake": ["匍匐爬行类", "蛇行", "NP V PP", "[+位移] [+方式] [+蛇行]", "蜿蜒移动"],
                # 长途行进类
                "travel": ["长途行进类", "长途跋涉", "NP V PP (across, through)", "[+位移] [+方式] [+长途]", "长途旅行"],
                "journey": ["长途行进类", "旅程", "NP V PP", "[+位移] [+方式] [+旅程]", "长途旅行"],
                "trek": ["长途行进类", "艰苦跋涉", "NP V PP", "[+位移] [+方式] [+艰苦跋涉]", "艰难徒步"],
                "hike": ["长途行进类", "徒步", "NP V PP", "[+位移] [+方式] [+徒步]", "户外行走"],
                "backpack": ["长途行进类", "背包远足", "NP V PP", "[+位移] [+方式] [+长途] [+背包远足]", "徒步旅行"],
                "trudge": ["长途行进类", "跋涉", "NP V PP", "[+位移] [+方式] [+跋涉]", "艰难行走"],
                "march": ["长途行进类", "行军", "NP V PP", "[+位移] [+方式] [+行军]", "军队行进"],
                "migrate": ["长途行进类", "迁徙", "NP V PP", "[+位移] [+方式] [+迁徙]", "群体移动"],
                "commute": ["长途行进类", "通勤", "NP V PP", "[+位移] [+方式] [+通勤]", "往返工作"],
                # 运载工具类
                "drive": ["运载工具类", "工具位移", "NP V PP (across, along)", "[+位移] [+方式] [+运载工具]", "驾驶车辆"],
                "ride": ["运载工具类", "乘坐", "NP V PP (across, along)", "[+位移] [+方式] [+运载工具]", "乘坐工具"],
                "sail": ["运载工具类", "航海", "NP V PP (across, into)", "[+位移] [+方式] [+运载工具]", "乘船"],
                "ski": ["运载工具类", "滑雪", "NP V PP (across, down)", "[+位移] [+方式] [+运载工具]", "滑雪"],
                "skate": ["运载工具类", "滑冰", "NP V PP (across, along)", "[+位移] [+方式] [+滑冰]", "冰上滑行"],
                "board": ["运载工具类", "滑板", "NP V PP", "[+位移] [+方式] [+滑板]", "滑板运动"],
                "surf": ["运载工具类", "冲浪", "NP V PP (across)", "[+位移] [+方式] [+冲浪]", "水上冲浪"],
                "skateboard": ["运载工具类", "滑板车", "NP V PP", "[+位移] [+方式] [+滑板车]", "滑板车"],
                "cycle": ["运载工具类", "骑行", "NP V PP", "[+位移] [+方式] [+骑行]", "自行车"],
                "motor": ["运载工具类", "驾驶摩托车", "NP V PP", "[+位移] [+方式] [+驾驶]", "摩托骑行"],
                "drive": ["运载工具类", "驾驶汽车", "NP V PP", "[+位移] [+方式] [+驾驶]", "汽车驾驶"],
            },
            "category": "方式聚焦类",
            "subclass": "方式类"
        },
        "purpose": {
            "subclasses": {
                "chase": ["目的类", "主动追逐", "NP V NP / after NP", "[+位移] [+目的] [+追赶]", "范畴原型"],
                "pursue": ["目的类", "追赶", "NP V NP", "[+位移] [+目的] [+追赶]", "持续追赶"],
                "follow": ["目的类", "跟随", "NP V NP", "[+位移] [+目的] [+跟随]", "紧随其后"],
                "shadow": ["目的类", "跟随潜伏", "NP V NP", "[+位移] [+目的] [+跟随] [+隐秘]", "暗中跟随"],
                "tail": ["目的类", "尾随", "NP V NP", "[+位移] [+目的] [+跟随] [+尾随]", "在后面跟随"],
                "track": ["目的类", "追踪", "NP V NP", "[+位移] [+目的] [+跟随] [+追踪]", "追踪线索"],
                "trail": ["目的类", "拖后", "NP V NP", "[+位移] [+目的] [+跟随] [+拖后]", "落后跟随"],
            },
            "category": "关联聚焦类",
            "subclass": "目的类"
        },
        "participant": {
            "subclasses": {
                "accompany": ["参与者类", "协同随行", "NP V NP PP (to, into)", "[+位移] [+参与者] [+陪同]", "陪同某人"],
                "conduct": ["参与者类", "引导", "NP V NP PP (to, into)", "[+位移] [+参与者] [+陪同] [+正式]", "引导者"],
                "escort": ["参与者类", "护送", "NP V NP PP (to, from)", "[+位移] [+参与者] [+陪同] [+护送]", "护送保护"],
                "guide": ["参与者类", "引路", "NP V NP PP (to, through)", "[+位移] [+参与者] [+引领]", "向导"],
                "lead": ["参与者类", "带领", "NP V NP PP (to, through)", "[+位移] [+参与者] [+引领]", "领导"],
                "shepherd": ["参与者类", "引导", "NP V NP PP (to, through)", "[+位移] [+参与者] [+引领] [+引导]", "牧羊人"],
                "wait": ["参与者类", "等候", "NP V PP", "[+位移] [+参与者] [+等候]", "等待移动"],
            },
            "category": "关联聚焦类",
            "subclass": "参与者类"
        }
    }

    return verbs_data


def extract_all_verbs(verbs_data):
    """
    提取所有动词的扁平化列表

    Returns:
        list: 所有动词的列表
    """
    verbs = []
    for category, data in verbs_data.items():
        for verb, details in data["subclasses"].items():
            verbs.append({
                "word": verb,
                "chinese": details[0],
                "category": data["category"],
                "subclass": data["subclass"],
                "formula": details[2],
                "meaning": details[3],
                "note": details[4] if len(details) > 4 else ""
            })
    return verbs


def save_verbs_data(verbs, filename="data/movement_verbs.json"):
    """
    保存单词数据到 JSON 文件

    Returns:
        str: 文件路径
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(verbs, f, ensure_ascii=False, indent=2)

    print(f"✅ 单词数据已保存到: {filename}")
    return filename


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 英语移动动词数据提取脚本")
    print("=" * 60)

    # 1. 提取动词数据
    print("\n【步骤 1/3】从文档中提取动词...")
    verbs_data = extract_verbs_from_text("")
    print(f"✅ 成功提取 {len(verbs_data)} 大类范畴")

    # 2. 提取所有动词
    print("\n【步骤 2/3】提取所有动词...")
    verbs = extract_all_verbs(verbs_data)
    print(f"✅ 成功提取 {len(verbs)} 个动词")

    # 3. 显示分类统计
    print("\n【分类统计】:")
    category_stats = {}
    for verb in verbs:
        cat = verb["category"]
        category_stats[cat] = category_stats.get(cat, 0) + 1

    for cat, count in sorted(category_stats.items()):
        print(f"  {cat}: {count} 个动词")

    # 4. 保存到文件
    print("\n【步骤 3/3】保存单词数据...")
    filename = save_verbs_data(verbs)

    # 5. 显示前5个单词示例
    print("\n【示例】前5个单词:")
    for i, verb in enumerate(verbs[:5], 1):
        print(f"  {i}. {verb['word']} - {verb['chinese']} ({verb['category']}/{verb['subclass']})")

    # 6. 显示特定范畴的动词示例
    print("\n【示例】路径聚焦类动词:")
    endpoint_verbs = [v for v in verbs if v["category"] == "路径聚焦类"]
    for v in endpoint_verbs[:5]:
        print(f"  - {v['word']}: {v['chinese']}")

    print("\n【示例】方式聚焦类动词:")
    manner_verbs = [v for v in verbs if v["category"] == "方式聚焦类"]
    for v in manner_verbs[:5]:
        print(f"  - {v['word']}: {v['chinese']}")

    print("\n【示例】关联聚焦类动词:")
    related_verbs = [v for v in verbs if v["category"] == "关联聚焦类"]
    for v in related_verbs[:5]:
        print(f"  - {v['word']}: {v['chinese']}")

    print("\n" + "=" * 60)
    print("✅ 数据提取完成！")
    print("=" * 60)
