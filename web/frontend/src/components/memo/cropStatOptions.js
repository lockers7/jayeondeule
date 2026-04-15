export const CROP_STAT_OPTIONS = [
    {value: 0, label: "미정의"},
    {value: 10, label: "양호"},
    {value: 20, label: "갈변"},
    {value: 30, label: "물방울"},
    {value: 40, label: "생육더딤"},
    {value: 50, label: "벌레"},
];

export const getCropStatLabel = (value) => {
    const opt = CROP_STAT_OPTIONS.find(o => o.value === value);
    return opt ? opt.label : "";
};
