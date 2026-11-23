"""分析条目的输出结构（设计方案第 8 节）。

结构里没有 score / level / rank 一类字段，additionalProperties 关闭，
模型没有地方写分数，也不输出时间。
"""

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {"type": "string"},
                    "observation": {"type": "string"},
                    "suggestion": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "segment_id": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                            "required": ["segment_id", "quote"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["dimension", "observation", "suggestion", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

TITLES_SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["segment_id", "title"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["titles"],
    "additionalProperties": False,
}
