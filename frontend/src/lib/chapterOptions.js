export const GENERAL_CHAPTER_VALUE = "__general__";
export const GENERAL_CHAPTER_LABEL = "通用";

export function isGeneralChapterValue(value) {
  return String(value || "") === GENERAL_CHAPTER_VALUE;
}

export function toChapterMode(value) {
  return isGeneralChapterValue(value) ? "general" : "normal";
}

export function withGeneralChapterOption(chapters = []) {
  const rows = Array.isArray(chapters) ? chapters : [];
  const exists = rows.some((item) => String(item?.id || "") === GENERAL_CHAPTER_VALUE);
  if (exists) {
    return rows;
  }
  return [
    {
      id: GENERAL_CHAPTER_VALUE,
      stage: "senior",
      subject: "物理",
      grade: "通用",
      textbook: "系统",
      volume_code: "general",
      volume_name: GENERAL_CHAPTER_LABEL,
      volume_order: -1,
      chapter_order: -1,
      chapter_code: "0.0",
      chapter_keywords: [],
      title: GENERAL_CHAPTER_LABEL,
      is_enabled: true
    },
    ...rows
  ];
}
