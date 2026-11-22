/* ============================================================
   记忆面板 · 全局模糊搜索引擎（零依赖）
   5 层融合打分：
     1) 精确 / 前缀 / 子串 / 多词协同
     2) 中文无空格 2-gram 软覆盖
     3) 双向同义词与旧称别名库
     4) 常用汉字拼音全拼与首字母（含多音字）
     5) 1 字错字容错（Damerau-Levenshtein + 紧凑有序子序列）
   ============================================================ */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  }
  if (root && typeof root === "object") {
    root.MemorySearchEngine = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this, function () {
  "use strict";

  // 3,770 常用汉字（GB2312 一级字全集 + 配置 schema 与面板词表）按拼音音节分组
  const PINYIN_BY_SYLLABLE = {a:"啊阿",ai:"哀哎唉埃挨爱癌皑矮碍艾蔼隘",an:"俺安岸按暗案氨胺鞍",ang:"昂盎肮",ao:"傲凹奥懊敖澳熬翱袄",ba:"八叭吧坝巴扒把拔捌爸疤笆罢耙芭跋霸靶",bai:"佰拜摆柏白百稗败",ban:"伴办半扮扳拌搬斑板版班瓣绊般颁",bang:"傍帮梆棒榜磅绑膀蚌谤邦镑",bao:"保包堡宝报抱暴爆胞苞薄褒豹雹饱鲍",bei:"倍北卑呗备悲惫杯焙狈碑背被贝辈钡",ben:"奔本笨苯",beng:"崩泵甭绷蹦迸",bi:"壁币庇弊彼必敝比毕毖毙痹碧笔臂蓖蔽逼避鄙闭陛鼻",bian:"便卞变扁编贬辨辩辫边遍鞭",biao:"彪标膘表",bie:"别憋瘪鳖",bin:"宾彬摈斌滨濒",bing:"丙兵冰并柄炳病秉饼",bo:"伯剥勃博卜帛拨搏播波渤玻箔脖膊舶菠钵铂驳",bu:"不哺埠布怖捕步簿补部",ca:"擦",cai:"彩才材猜睬菜蔡裁财踩采",can:"参惨惭掺残灿蚕餐黪",cang:"仓沧舱苍藏",cao:"操曹槽糙草",ce:"侧册厕测策",ceng:"层曾蹭",cha:"叉察岔差插搽查碴茬茶诧",chai:"拆柴豺",chan:"产搀缠蝉谗铲阐颤馋",chang:"倡偿厂唱场尝常敞昌猖畅肠",chao:"吵嘲巢抄朝潮炒超钞",che:"彻扯掣撤澈车",chen:"尘忱晨沉臣衬趁辰郴陈",cheng:"乘呈城惩成承撑橙澄秤称程诚逞骋",chi:"侈吃尺弛持斥池炽痴翅耻赤迟驰齿",chong:"充冲宠崇虫",chou:"丑仇愁抽畴瞅稠筹绸臭踌酬",chu:"储出初厨处搐楚橱滁畜矗础触躇锄除雏",chuai:"揣",chuan:"串传喘川椽穿船",chuang:"创幢床疮窗闯",chui:"吹垂捶椎炊锤",chun:"唇春椿淳纯蠢醇",chuo:"戳绰",ci:"伺刺慈次此瓷疵磁茨词赐辞雌",cong:"丛从匆囱聪葱",cou:"凑",cu:"促簇粗醋",cuan:"窜篡蹿",cui:"催崔摧淬瘁粹翠脆",cun:"存寸村",cuo:"挫措搓撮磋错",da:"哒大打搭瘩答达",dai:"代傣呆带待怠戴歹殆袋贷逮",dan:"丹但单弹惮担掸旦氮淡耽胆蛋诞郸",dang:"党当挡档荡",dao:"倒刀到导岛悼捣盗祷稻蹈道",de:"得德的",deng:"凳灯登瞪等蹬邓",di:"低地堤嫡帝底弟抵敌涤滴狄笛第缔翟蒂迪递",dian:"佃典垫奠店惦掂殿淀滇点电甸碘靛颠",diao:"凋刁叼吊掉碉调钓雕",die:"叠爹碟蝶谍跌迭",ding:"丁叮定盯订钉锭顶鼎",diu:"丢",dong:"东侗冬冻动恫懂栋洞董",dou:"兜抖斗痘豆逗都陡",du:"堵妒度杜毒渡犊独督睹肚读赌镀",duan:"断段短端缎锻",dui:"兑堆对队",dun:"吨囤墩敦盾蹲遁钝顿",duo:"剁哆垛堕多夺惰掇朵舵跺躲",e:"俄厄娥峨恶扼蛾讹遏鄂额饿鹅",en:"恩",er:"二儿尔洱而耳贰饵",fa:"乏伐发法珐筏罚阀",fan:"凡反帆樊泛烦犯番矾繁翻范藩贩返钒饭",fang:"仿坊妨房放方纺肪芳访防",fei:"匪吠啡废沸肥肺菲诽费非飞",fen:"份分吩坟奋忿愤氛汾焚粉粪纷芬酚",feng:"丰冯凤奉封峰枫烽疯缝蜂讽逢锋风",fou:"否",fu:"付伏佛俘俯傅副咐复夫妇孵富幅府弗扶抚拂敷斧服氟浮涪父甫福符缚肤腐腑腹袱覆讣负赋赴辅辐釜阜附",ga:"嘎噶",gai:"改概溉盖该钙",gan:"干感敢杆柑甘秆竿肝赣赶",gang:"冈刚岗杠港纲缸肛钢",gao:"告搞皋稿篙糕羔膏镐高",ge:"个割各咯哥戈搁格歌疙胳葛铬阁隔革鸽",gei:"给",gen:"根跟",geng:"埂庚更梗羹耕耿",gong:"供公共功宫工巩弓恭拱攻汞贡躬龚",gou:"勾垢够构沟狗苟购钩",gu:"估古咕固姑孤故沽箍股菇蛊谷辜雇顾骨鼓",gua:"刮剐寡挂瓜褂",guai:"乖怪拐",guan:"关冠官惯棺灌管罐观贯馆",guang:"光广逛",gui:"傀刽圭归柜桂炔瑰癸硅规诡贵跪轨闺鬼龟",gun:"棍滚辊",guo:"国果裹过郭锅",ha:"哈蛤",hai:"亥孩害氦海还骇骸",han:"函含喊寒悍憨憾捍撼旱汉汗涵焊罕翰邯酣韩",hang:"夯杭航",hao:"号嚎壕好毫浩耗豪貉郝",he:"何合呵和喝核河涸盒禾荷菏褐贺赫阂鹤",hei:"嘿黑",hen:"很恨狠痕",heng:"亨哼恒横衡",hong:"哄宏弘洪烘红虹轰鸿",hou:"侯候厚后吼喉猴",hu:"乎互呼唬壶弧忽户护沪湖狐瑚糊胡葫虎蝴",hua:"划化华哗滑猾画花话",huai:"坏徊怀槐淮",huan:"唤宦幻患换桓欢涣焕环痪缓豢",huang:"凰幌恍惶慌晃煌皇磺簧荒蝗谎黄",hui:"会卉回徽恢悔惠慧挥晦毁汇灰烩秽绘蛔讳诲贿辉",hun:"婚昏浑混荤魂",huo:"伙惑或活火祸获豁货霍",ji:"伎冀几击剂即及吉圾基妓姬嫉季寂寄己忌急悸技挤既机极棘汲济激畸疾祭积稽箕籍级纪继绩缉肌脊蓟藉计讥记辑迹际集饥鸡",jia:"价佳假加嘉夹嫁家架枷甲稼茄荚贾钾颊驾",jian:"件俭健兼减剑剪坚奸尖建拣捡柬检歼涧渐溅煎监硷碱笺简箭缄肩舰艰茧荐见贱践鉴键间饯",jiang:"僵匠奖姜将桨江浆疆蒋讲酱降",jiao:"交侥剿叫娇搅教椒浇焦狡矫礁窖绞缴胶脚蕉角轿较郊酵铰饺骄",jie:"介借劫姐届戒截捷接揭杰洁界疥皆睫秸竭结节芥街解诫阶",jin:"仅今劲尽巾斤晋津浸烬禁筋紧襟谨近进金锦靳",jing:"井京兢净境径惊敬景晶痉睛竞竟粳精经茎荆警镜靖静颈鲸",jiong:"炯窘",jiu:"久九厩咎就揪救旧灸玖疚究纠臼舅酒韭",ju:"举俱具剧句咀局居巨惧拒拘据桔沮炬狙疽矩聚菊距踞锯鞠驹",juan:"倦卷娟捐眷绢鹃",jue:"倔决嚼抉掘撅攫爵绝觉诀",jun:"俊军君均峻浚竣菌郡钧骏",ka:"卡咖喀",kai:"凯开慨揩楷",kan:"刊勘坎堪槛看砍",kang:"亢康慷扛抗炕糠",kao:"拷烤考靠",ke:"克刻可咳坷壳客柯棵渴磕科苛课颗",ken:"啃垦恳肯",keng:"吭坑",kong:"孔恐控空",kou:"口寇扣抠",ku:"哭库枯窟苦裤酷",kua:"垮夸挎胯跨",kuai:"侩块快筷",kuan:"宽款",kuang:"况匡旷框狂眶矿筐",kui:"亏奎岿愧溃盔窥葵馈魁",kun:"困坤捆昆",kuo:"廓扩括阔",la:"啦喇垃拉腊蜡辣",lai:"来莱赖",lan:"兰婪岚懒拦揽栏滥澜烂篮缆蓝览谰阑",lang:"廊朗榔浪狼琅郎",lao:"佬劳姥捞涝潦烙牢老酪",le:"乐了肋",lei:"儡勒嘞垒擂泪磊类累蕾镭雷",leng:"冷棱楞",li:"丽例俐傈利力励历厉厘吏哩李栗梨沥漓犁狸理璃痢砾礼离立篱粒荔莉里隶鲤黎",lia:"俩",lian:"帘廉怜恋敛涟炼练联脸莲连链镰",liang:"两亮凉晾梁粮粱良谅辆量",liao:"僚寥廖撂撩料燎疗聊辽镣",lie:"列劣烈猎裂",lin:"临凛吝拎林淋琳磷赁邻霖鳞",ling:"令伶凌另岭灵玲羚菱铃陵零领龄",liu:"六刘柳榴流浏溜琉留瘤硫馏",long:"咙垄拢窿笼聋陇隆龙",lou:"娄搂楼漏篓陋",lu:"卢卤庐录戮掳潞炉碌禄芦虏赂路陆露颅鲁鹿麓",luan:"乱卵孪峦挛滦",lun:"仑伦抡沦纶论轮",luo:"啰洛箩络罗萝落螺裸逻锣骆骡",lv:"侣吕屡履律旅氯滤率绿缕虑铝驴",lve:"掠略",ma:"吗嘛妈玛码蚂马骂麻",mai:"买卖埋脉迈麦",man:"慢曼满漫瞒蔓蛮谩馒",mang:"忙氓盲芒茫莽",mao:"冒卯帽毛猫矛茂茅貌贸铆锚",me:"么",mei:"妹媒媚寐昧枚梅每没煤玫眉美酶镁霉",men:"们门闷",meng:"孟梦檬猛盟萌蒙锰",mi:"密幂弥泌眯秘米糜蜜觅谜迷醚靡",mian:"免冕勉娩棉眠绵缅面",miao:"喵妙庙描渺瞄秒苗藐",mie:"灭蔑",min:"悯抿敏民皿闽",ming:"冥名命明螟铭鸣",miu:"谬",mo:"墨寞抹摩摸摹末模沫漠磨膜莫蘑陌魔默",mou:"某牟谋",mu:"亩募墓姆幕慕拇暮木母牡牧目睦穆",n:"嗯",na:"呐哪娜拿纳那钠",nai:"乃奈奶氖耐",nan:"南男难",nang:"囊",nao:"恼挠淖脑闹",ne:"呢",nei:"内馁",nen:"嫩",neng:"能",ni:"你倪匿妮尼拟昵泥溺腻逆霓",nian:"年念拈捻撵碾蔫辗",niang:"娘酿",niao:"尿鸟",nie:"啮孽捏涅聂镊镍",nin:"您",ning:"凝宁拧柠泞狞",niu:"扭牛纽钮",nong:"农弄浓脓",nu:"努奴怒",nuan:"暖",nuo:"懦挪糯诺",nv:"女",nve:"疟虐",o:"哦",ou:"偶呕欧殴沤藕鸥",pa:"啪帕怕爬琶趴",pai:"徘拍排派湃牌",pan:"判叛攀潘畔盘盼磐",pang:"乓庞旁耪胖",pao:"刨咆抛泡炮袍跑",pei:"佩呸培沛胚裴赔配陪",pen:"喷盆",peng:"彭抨捧朋棚澎烹砰硼碰篷膨蓬鹏",pi:"僻劈匹啤坯屁批披毗琵疲痞皮砒脾譬辟霹",pian:"偏片篇骗",piao:"漂瓢票缥飘",pie:"撇瞥",pin:"品拼聘贫频",ping:"乒凭坪屏平瓶苹萍评",po:"坡婆泊泼破粕迫颇魄",pou:"剖",pu:"仆圃埔扑普曝朴浦瀑脯莆菩葡蒲谱铺",qi:"七乞企其凄启器奇契妻岂崎弃戚旗期柒栖棋欺歧气汽沏泣漆畦砌祁祈脐讫起迄骑齐",qia:"恰掐洽",qian:"乾仟倩前千堑嵌扦欠歉浅潜牵签谦谴迁遣钎钱钳铅黔",qiang:"呛墙强抢枪羌腔蔷",qiao:"乔侨俏峭巧悄撬敲桥橇瞧窍翘锹鞘",qie:"且切怯窃",qin:"亲侵勤寝擒沁琴禽秦芹钦",qing:"倾卿庆情擎晴氢氰清请轻青顷",qiong:"琼穷",qiu:"丘囚求泅球秋邱酋",qu:"区去取娶屈曲渠蛆趋趣躯驱龋",quan:"全券劝圈拳权泉犬痊醛颧",que:"却榷瘸确缺雀鹊",qun:"群裙",ran:"冉染然燃",rang:"嚷壤攘瓤让",rao:"扰绕饶",re:"惹热",ren:"人仁任刃壬妊忍纫认韧",reng:"仍扔",ri:"日",rong:"冗容戎溶熔绒茸荣蓉融",rou:"揉柔肉",ru:"乳儒入如孺汝茹蠕褥辱",ruan:"软阮",rui:"瑞蕊锐",run:"润闰",ruo:"弱若",sa:"撒洒萨",sai:"塞腮赛鳃",san:"三伞叁散",sang:"丧嗓桑",sao:"嫂扫搔骚",se:"涩瑟色",sen:"森",seng:"僧",sha:"傻刹厦啥杀沙煞砂纱莎",shai:"晒筛",shan:"删善山扇擅杉汕煽珊缮膳苫衫赡闪陕",shang:"上伤商墒尚晌裳赏",shao:"勺哨少捎梢烧稍绍芍邵韶",she:"奢射慑摄涉社舌舍蛇设赊赦",shen:"什伸呻娠婶审慎沈深渗甚申砷神绅肾身",sheng:"剩升圣声牲生甥盛省绳胜",shi:"世事仕似使侍势匙十史嗜噬士失始实室尸屎市师式恃拭拾施时是柿氏湿狮矢石示虱蚀视誓识试诗适逝释食饰驶",shou:"兽受售守寿手授收瘦首",shu:"书叔墅孰属庶恕戍抒数暑曙术束枢树梳殊淑漱熟疏竖署舒蔬薯蜀赎输述黍鼠",shua:"刷耍",shuai:"帅摔甩衰",shuan:"拴栓",shuang:"双爽霜",shui:"水睡税谁",shun:"吮瞬舜顺",shuo:"朔烁硕说",si:"丝司嗣嘶四寺巳思撕斯死私肆饲",song:"宋怂松耸讼诵送颂",sou:"嗽搜擞艘",su:"俗僳塑宿溯粟素肃苏诉速酥",suan:"算蒜酸",sui:"岁碎祟穗绥虽遂隋随隧髓",sun:"孙损笋",suo:"唆所梭琐索缩蓑锁",ta:"他塌塔她它挞獭踏蹋",tai:"台太态抬汰泰胎苔酞",tan:"叹坍坛坦探摊檀毯滩潭炭痰瘫碳袒谈谭贪",tang:"倘唐堂塘搪棠汤淌烫糖膛趟躺",tao:"套掏桃涛淘滔绦萄讨逃陶",te:"特",teng:"疼腾藤誊",ti:"体剃剔啼嚏屉惕提替梯涕踢蹄锑题",tian:"填天恬添甜田腆舔",tiao:"挑条眺跳迢",tie:"帖贴铁",ting:"亭停厅听庭廷挺汀烃艇",tong:"同彤捅桐桶痛瞳童筒统通酮铜",tou:"偷头投透",tu:"兔凸吐图土屠徒涂秃突途",tuan:"团湍",tui:"推腿蜕褪退颓",tun:"吞屯臀",tuo:"唾妥托拓拖椭脱陀驮驼鸵",wa:"哇娃挖洼瓦蛙袜",wai:"外歪",wan:"万丸婉完宛弯惋挽晚湾烷玩皖碗腕豌顽",wang:"亡妄往忘旺望枉汪王网",wei:"为伟伪位卫危味唯喂围委威尉尾巍微惟慰未桅渭潍畏纬维胃苇萎蔚谓违韦魏",wen:"吻文温瘟稳紊纹蚊问闻",weng:"嗡瓮翁",wo:"卧我挝握斡沃涡窝蜗",wu:"乌五伍侮务勿午吴吾呜坞屋巫悟戊捂无晤梧武毋污物舞芜诬误钨雾",xi:"习吸喜嘻夕媳希席息悉惜戏昔晰析檄汐洗溪烯熄熙牺犀矽硒稀系细膝袭西铣锡隙",xia:"下侠匣吓夏峡暇狭瞎虾辖霞",xian:"仙先县咸嫌宪弦掀显涎献现纤线羡腺舷衔贤锨闲限险陷馅鲜",xiang:"乡享像厢向响巷想橡湘相祥箱翔襄详象镶项香",xiao:"哮啸嚣孝宵小效晓校消淆硝笑肖萧销霄",xie:"些写协卸屑懈挟携斜械楔歇泄泻胁蝎蟹谐谢邪鞋",xin:"信心忻新欣芯薪衅辛锌",xing:"兴刑型姓幸形性惺星杏猩腥行邢醒",xiong:"兄凶匈汹熊胸雄",xiu:"休修嗅朽秀绣羞袖锈",xu:"叙吁嘘墟婿序徐恤戌旭絮绪续蓄虚许酗需须",xuan:"喧宣悬旋渲玄癣眩绚轩选",xue:"削学穴薛血雪靴",xun:"勋寻巡循旬殉汛熏训讯询迅逊驯",ya:"丫亚压呀哑崖押涯牙芽蚜衙讶轧雅鸦鸭",yan:"严厌咽唁堰奄宴岩延彦掩沿淹演炎烟焉焰燕盐眼研砚艳蜒衍言谚阉阎雁颜验",yang:"仰佯养央扬杨样殃氧洋漾疡痒秧羊阳鸯",yao:"咬妖姚尧摇瑶窑耀腰舀药要谣遥邀钥",ye:"业也冶叶噎夜掖曳椰液爷耶腋野页",yi:"一义乙亦亿以仪伊依倚医壹夷姨宜屹已异彝役忆意抑揖易椅毅沂溢疑疫益矣移绎翌翼肄胰臆艺蚁衣裔议译诣谊逸遗邑铱颐",yin:"印吟因姻寅尹引殷淫茵荫银阴隐音饮",ying:"婴应影映樱盈硬缨英荧莹萤营蝇赢迎颖鹰",yo:"哟",yong:"佣勇咏庸恿拥永泳涌用痈臃蛹踊雍",you:"优佑又友右尤幼幽忧悠有油游犹由诱邮酉釉铀",yu:"与予于余俞喻域娱宇寓屿峪御愈愉愚榆欲浴淤渔渝狱玉盂禹羽育舆芋虞裕誉语豫迂逾遇郁阈隅雨预驭鱼",yuan:"元冤原员园圆垣怨愿援渊源猿缘苑袁辕远院鸳",yue:"岳悦曰月粤约越跃阅",yun:"云允匀孕晕耘蕴运郧酝陨韵",za:"匝咋杂砸",zai:"仔再哉在宰栽灾载",zan:"咱攒暂赞",zang:"脏葬赃",zao:"凿噪早枣澡灶燥皂糟藻蚤躁造遭",ze:"则择泽责",zei:"贼",zen:"怎",zeng:"增憎赠",zha:"乍喳扎札柞栅榨渣炸眨诈铡闸",zhai:"债宅寨摘斋窄",zhan:"占展崭战斩栈毡沾湛盏瞻站粘绽蘸詹",zhang:"丈仗帐张彰掌杖樟涨漳瘴章胀账长障",zhao:"兆召找招昭沼照爪罩肇赵",zhe:"哲折浙着者蔗蛰辙这遮锗",zhen:"侦帧振斟枕珍甄疹真砧臻诊贞针镇阵震",zheng:"争征怔拯挣政整正狰症睁蒸证郑",zhi:"之侄值制只吱址峙帜志执指挚掷支旨智枝植止殖汁治滞炙痔直知秩稚窒纸织置职肢脂至致芝蜘质趾",zhong:"中仲众忠盅种终肿衷重钟",zhou:"周咒宙州帚昼洲皱粥肘舟诌轴骤",zhu:"主住助嘱拄朱柱株注烛煮猪珠瞩祝竹筑著蛀蛛诛诸贮逐铸驻",zhua:"抓",zhuai:"拽",zhuan:"专撰砖篆赚转",zhuang:"壮妆庄撞桩状装",zhui:"坠缀赘追锥",zhun:"准谆",zhuo:"卓啄拙捉桌浊灼茁酌",zi:"兹咨姿子字孜淄渍滋滓籽紫自资",zong:"宗总棕纵综踪鬃",zou:"奏揍走邹",zu:"卒族祖租组诅足阻",zuan:"纂钻",zui:"嘴最罪醉",zun:"尊遵",zuo:"佐作做坐左座昨琢"};

  // 高频多音字补充读音：保证「重排(chongpai)」「长期(changqi)」「调整(tiaozheng)」「倍率(beilu)」等均可双向命中
  const POLYPHONE_ALTS = {
    重: ["chong"],
    调: ["tiao"],
    长: ["chang"],
    行: ["hang"],
    藏: ["zang"],
    传: ["zhuan"],
    还: ["huan"],
    率: ["lu", "shuai"],
    降: ["xiang"],
    单: ["shan"],
    查: ["zha"],
    省: ["xing"],
    校: ["jiao"],
    差: ["chai"],
    称: ["chen"],
    弹: ["tan"],
    秘: ["bi"],
    露: ["lou"],
    卡: ["qia"],
    模: ["mu"],
    数: ["shuo"],
    读: ["dou"],
    觉: ["jiao"],
    嗯: ["en"],
    绿: ["lu"],
    滤: ["lu"],
    略: ["lue"],
    女: ["nu"],
  };

  // 双向同义词 / 旧称 / 大白话意图词典
  const DEFAULT_SYNONYMS = [
    [
      "向量存储精度",
      "向量精度",
      "存储精度",
      "vector_precision",
      "vector_storage_precision",
      "float16",
      "float32",
      "fp16",
      "fp32",
      "半精度",
      "半精度省流",
      "单精度",
      "标准精度",
      "省内存",
      "省空间",
      "瘦身",
      "低配",
      "低内存",
      "低配云服",
    ],
    [
      "拟人化记忆",
      "拟人化记忆表达",
      "拟人化",
      "模糊记忆",
      "模糊印象",
      "诚实提示",
      "想不起来",
      "细节清晰期",
      "轮廓印象期",
      "memory_humanization",
      "humanization",
    ],
    [
      "记得这个人",
      "人物卡",
      "人物记忆",
      "她记得的人",
      "分量",
      "她心里有杆秤",
      "刻骨",
      "称呼",
      "persona_memory",
      "imprint",
      "weight",
    ],
    [
      "跨群",
      "跨窗口",
      "群聊衔接",
      "群聊衔接到其他群聊",
      "群到群",
      "群聊到私聊",
      "私聊到群聊",
      "串话",
      "防串话",
      "连续对话",
      "话题衔接",
      "cross_window",
      "cross_window_group_to_group_enabled",
      "conversation_memory",
    ],
    [
      "待复核",
      "小黑屋",
      "待审核",
      "隔离",
      "隔离区",
      "隔离批次",
      "pending",
      "quarantine",
      "hide_pending_review",
      "review_status",
    ],
    [
      "旧版记忆迁移",
      "旧版迁移",
      "历史迁移",
      "导入旧库",
      "旧库导入",
      "livingmemory",
      "livingmemory迁移",
      "livingmemory导入",
      "livingmemory_migration",
      "migration",
    ],
    [
      "跨平台身份",
      "跨平台",
      "合并账号",
      "同一人",
      "账号合并",
      "merge_platform_accounts",
    ],
    [
      "嵌入",
      "向量",
      "向量召回",
      "向量搜索",
      "向量缓存",
      "快照缓存",
      "语料预热",
      "embedding",
      "vector",
      "warmup",
      "snapshot",
    ],
    [
      "重排",
      "精排",
      "二阶段排序",
      "重排熔断",
      "rerank",
      "reranker",
    ],
    [
      "检索",
      "检索进阶",
      "召回",
      "记忆召回",
      "相似度",
      "多样性",
      "去冗余",
      "retrieval",
      "recall",
      "mmr",
      "top_k",
    ],
    [
      "记忆摘要",
      "长期记忆总结",
      "总结",
      "摘要",
      "总结模型",
      "摘要模型",
      "备用模型",
      "回退模型",
      "自动消化",
      "积压",
      "memory_summary",
      "summary",
      "provider",
      "fallback",
      "auto_drain",
    ],
    [
      "统一画像",
      "用户画像",
      "画像",
      "智能画像",
      "portrait",
      "profile",
    ],
    [
      "记忆断言",
      "断言",
      "断言层",
      "memory_assertions",
      "assertion",
    ],
    [
      "核心记忆",
      "常驻记忆",
      "核心规则",
      "边界",
      "偏好",
      "core_memory",
    ],
    [
      "外观",
      "配色主题",
      "主题",
      "配色",
      "传统色",
      "色板",
      "月白",
      "天缥",
      "打开方式",
      "三维终端",
      "控制台",
      "appearance",
      "theme",
      "palette",
      "ui_style",
    ],
    [
      "可见性",
      "隐私",
      "权限",
      "权限拓扑",
      "卡片权限",
      "隔离",
      "安全键",
      "范围控制",
      "私聊开关",
      "群聊开关",
      "visibility",
      "acl",
      "scope_control",
    ],
    [
      "陪伴桥接",
      "记忆插件协同",
      "陪伴插件",
      "我会永远陪着你",
      "联动",
      "桥接",
      "日程快速上下文",
      "穿搭快速上下文",
      "情绪连续性",
      "private_companion_bridge",
      "bridge",
      "companion",
    ],
    [
      "记忆衰减",
      "自然衰减",
      "遗忘",
      "自然遗忘",
      "先淡再忘",
      "褪色",
      "冷归档",
      "maintenance_decay",
      "decay",
    ],
    [
      "维护",
      "清理",
      "备份",
      "睡眠维护",
      "保留天数",
      "wal",
      "wal截断",
      "maintenance",
      "backup",
      "retention",
    ],
    [
      "记忆审计",
      "审计",
      "可回滚记忆审计",
      "回滚",
      "修正建议",
      "maintenance_audit",
      "audit",
      "rollback",
    ],
    [
      "历史聊天导入",
      "历史对话整理导入",
      "聊天记录",
      "历史导入",
      "导入聊天",
      "qq历史",
      "historical_chat_import",
      "chatimport",
    ],
    [
      "原文语义",
      "原文语义索引",
      "原文索引",
      "source_semantic",
    ],
    [
      "记忆注入",
      "记忆注入包",
      "注入",
      "注入日志",
      "字数上限",
      "预算",
      "memory_injection",
      "injection",
    ],
    [
      "上下文编排",
      "上下文编排进阶",
      "注入编排",
      "分槽",
      "意图上下文",
      "context_orchestration",
      "orchestration",
    ],
    [
      "记忆工具",
      "主动记忆工具",
      "回忆工具",
      "陪伴笔记工具",
      "分量工具",
      "memory_tools",
      "tool",
    ],
    [
      "记忆重建",
      "主动记忆重建",
      "证据导航",
      "多跳",
      "原文批读",
      "memory_reconstruction",
      "reconstruction",
    ],
    [
      "知识图谱",
      "图谱关联",
      "图谱",
      "关系边",
      "一跳扩展",
      "knowledge_graph",
      "graph",
    ],
    [
      "记忆捕获",
      "捕获",
      "记录消息",
      "稳定事实",
      "提议模式",
      "memory_capture",
      "capture",
    ],
    [
      "启动",
      "启动行为",
      "宽限期",
      "延迟启动",
      "后台任务",
      "startup",
      "background_grace_seconds",
    ],
  ];

  let charPinyinMap = null;

  function ensurePinyinMap() {
    if (charPinyinMap) return charPinyinMap;
    const map = Object.create(null);
    const syllables = Object.keys(PINYIN_BY_SYLLABLE);
    for (let i = 0; i < syllables.length; i += 1) {
      const syl = syllables[i];
      const chars = PINYIN_BY_SYLLABLE[syl];
      for (let j = 0; j < chars.length; j += 1) {
        map[chars[j]] = syl;
      }
    }
    charPinyinMap = map;
    return map;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function isCjkChar(ch) {
    const code = ch.charCodeAt(0);
    return code >= 0x4e00 && code <= 0x9fff;
  }

  function hasCjk(text) {
    return /[\u4e00-\u9fff]/.test(text);
  }

  function normalize(text) {
    return String(text ?? "")
      .toLowerCase()
      .replace(/[\u3000\s]+/g, " ")
      .trim();
  }

  function compactText(text) {
    return normalize(text).replace(/[\s_\-./:：·•、，,。！？!?「」『』（）()【】[\]《》〈〉"'`~]+/g, "");
  }

  function splitKeyWords(text) {
    return normalize(text)
      .replace(/[_\-./]+/g, " ")
      .replace(/[^a-z0-9\u4e00-\u9fff ]+/g, " ")
      .split(/\s+/)
      .filter(Boolean);
  }

  function extractCjkChunks(text) {
    const matches = String(text ?? "").match(/[\u4e00-\u9fff]+/g);
    return matches ? matches : [];
  }

  function bigrams(text) {
    const set = new Set();
    const chunks = extractCjkChunks(text);
    for (let i = 0; i < chunks.length; i += 1) {
      const chunk = chunks[i];
      for (let j = 0; j + 1 < chunk.length; j += 1) {
        set.add(chunk.slice(j, j + 2));
      }
    }
    return set;
  }

  function charReadings(ch) {
    const map = ensurePinyinMap();
    const primary = map[ch];
    if (!primary) return null;
    const alts = POLYPHONE_ALTS[ch];
    if (!alts) return [primary];
    const out = [primary];
    for (let i = 0; i < alts.length; i += 1) {
      if (out.indexOf(alts[i]) < 0) out.push(alts[i]);
    }
    return out;
  }

  function toPinyin(text) {
    const src = String(text ?? "");
    const primarySyls = [];
    const altSyls = [];
    const charSpans = []; // 仅记录有拼音/字母数字的字符索引，便于将拼音命中反标回原文
    let hasAlt = false;

    for (let i = 0; i < src.length; i += 1) {
      const ch = src[i];
      if (isCjkChar(ch)) {
        const readings = charReadings(ch);
        if (readings && readings.length) {
          primarySyls.push(readings[0]);
          const second = readings.length > 1 ? readings[1] : readings[0];
          altSyls.push(second);
          if (second !== readings[0]) hasAlt = true;
          charSpans.push({ index: i, char: ch, syl: readings[0], alt: second });
        }
      } else if (/[a-zA-Z0-9]/.test(ch)) {
        const lower = ch.toLowerCase();
        primarySyls.push(lower);
        altSyls.push(lower);
        charSpans.push({ index: i, char: ch, syl: lower, alt: lower });
      }
    }

    const full = primarySyls.join("");
    const initials = primarySyls.map((s) => s[0] || "").join("");
    const fulls = full ? [full] : [];
    const initialsList = initials ? [initials] : [];

    if (hasAlt) {
      const altFull = altSyls.join("");
      const altInit = altSyls.map((s) => s[0] || "").join("");
      if (altFull && fulls.indexOf(altFull) < 0) fulls.push(altFull);
      if (altInit && initialsList.indexOf(altInit) < 0) initialsList.push(altInit);
      // 逐字单替换前 2 个多音字，覆盖混合短语（如「重排」+「长期」组合）
      let swapped = 0;
      for (let i = 0; i < charSpans.length && swapped < 2; i += 1) {
        if (charSpans[i].alt !== charSpans[i].syl) {
          swapped += 1;
          const variant = primarySyls.slice();
          variant[i] = charSpans[i].alt;
          const vf = variant.join("");
          const vi = variant.map((s) => s[0] || "").join("");
          if (fulls.indexOf(vf) < 0) fulls.push(vf);
          if (initialsList.indexOf(vi) < 0) initialsList.push(vi);
        }
      }
    }

    return {
      full,
      initials,
      fulls,
      initialsList,
      charSpans,
      source: src,
    };
  }

  function mapInitialSpanToSource(pyInfo, startPos, len) {
    if (!pyInfo || !pyInfo.charSpans || !pyInfo.charSpans.length) return "";
    const endPos = startPos + len - 1;
    if (startPos < 0 || endPos >= pyInfo.charSpans.length) return "";
    const fromIdx = pyInfo.charSpans[startPos].index;
    const toIdx = pyInfo.charSpans[endPos].index + 1;
    return pyInfo.source.slice(fromIdx, toIdx);
  }

  function mapFullPinyinSpanToSource(pyInfo, matchedFull, startCharPos, len, useAlt) {
    if (!pyInfo || !pyInfo.charSpans || !pyInfo.charSpans.length) return "";
    const targetEnd = startCharPos + len;
    let cursor = 0;
    let firstIdx = -1;
    let lastIdx = -1;
    for (let i = 0; i < pyInfo.charSpans.length; i += 1) {
      const span = pyInfo.charSpans[i];
      const syl = useAlt ? span.alt : span.syl;
      const next = cursor + syl.length;
      if (next > startCharPos && cursor < targetEnd) {
        if (firstIdx < 0) firstIdx = span.index;
        lastIdx = span.index + 1;
      }
      cursor = next;
    }
    return firstIdx >= 0 && lastIdx > firstIdx ? pyInfo.source.slice(firstIdx, lastIdx) : "";
  }

  // 有界 Damerau-Levenshtein 距离（一维滚动数组零分配 + 字符频次快速剪枝）
  function editDistance(a, b, maxDist) {
    const limit = maxDist === undefined ? 1 : maxDist;
    const la = a.length;
    const lb = b.length;
    if (Math.abs(la - lb) > limit) return limit + 1;
    if (a === b) return 0;
    if (!la) return lb;
    if (!lb) return la;

    // 快速公共字符下界剪枝：最多允许 limit 次差异
    let missing = 0;
    for (let i = 0; i < la; i += 1) {
      if (b.indexOf(a[i]) < 0) {
        missing += 1;
        if (missing > limit) return limit + 1;
      }
    }

    let prevPrev = new Int16Array(lb + 1);
    let prev = new Int16Array(lb + 1);
    let curr = new Int16Array(lb + 1);
    for (let j = 0; j <= lb; j += 1) prev[j] = j;

    for (let i = 1; i <= la; i += 1) {
      curr[0] = i;
      let rowMin = i;
      const ai = a.charCodeAt(i - 1);
      const aPrev = i > 1 ? a.charCodeAt(i - 2) : -1;
      for (let j = 1; j <= lb; j += 1) {
        const bj = b.charCodeAt(j - 1);
        const cost = ai === bj ? 0 : 1;
        let val = prev[j] + 1;
        const ins = curr[j - 1] + 1;
        const sub = prev[j - 1] + cost;
        if (ins < val) val = ins;
        if (sub < val) val = sub;
        if (i > 1 && j > 1 && ai === b.charCodeAt(j - 2) && aPrev === bj) {
          const trans = prevPrev[j - 2] + 1;
          if (trans < val) val = trans;
        }
        curr[j] = val;
        if (val < rowMin) rowMin = val;
      }
      if (rowMin > limit) return limit + 1;
      const tmp = prevPrev;
      prevPrev = prev;
      prev = curr;
      curr = tmp;
    }
    return prev[lb];
  }

  function findFuzzySubstring(query, target, maxDist) {
    if (!query || !target) return null;
    const qLen = query.length;
    if (target.length < Math.max(2, qLen - maxDist)) return null;
    if (target.indexOf(query) >= 0) return { dist: 0, slice: query };

    // 整串快速字符存在性预筛：至少应有 qLen - maxDist 个查询字符出现在 target 中
    let present = 0;
    for (let i = 0; i < qLen; i += 1) {
      if (target.indexOf(query[i]) >= 0) present += 1;
    }
    if (present < qLen - maxDist) return null;

    let bestDist = maxDist + 1;
    let bestSlice = "";
    const minWin = Math.max(2, qLen - maxDist);
    const maxWin = Math.min(target.length, qLen + maxDist);
    for (let win = minWin; win <= maxWin; win += 1) {
      for (let start = 0; start + win <= target.length; start += 1) {
        const sub = target.slice(start, start + win);
        const d = editDistance(query, sub, maxDist);
        if (d < bestDist) {
          bestDist = d;
          bestSlice = sub;
          if (d === 0) return { dist: 0, slice: bestSlice };
        }
      }
    }
    return bestDist <= maxDist ? { dist: bestDist, slice: bestSlice } : null;
  }

  function tightSubsequence(query, target) {
    if (!query || !target || query.length > target.length) return null;
    let qi = 0;
    let first = -1;
    let last = -1;
    const hits = [];
    for (let ti = 0; ti < target.length && qi < query.length; ti += 1) {
      if (target[ti] === query[qi]) {
        if (first < 0) first = ti;
        last = ti;
        hits.push(target[ti]);
        qi += 1;
      }
    }
    if (qi !== query.length) return null;
    const span = last - first + 1;
    const maxSpan = Math.max(query.length + 3, Math.ceil(query.length * 2.4));
    if (span > maxSpan) return null;
    return { first, last, span, ratio: query.length / span, chars: hits };
  }

  function buildSynonymIndex(extraGroups) {
    const groups = DEFAULT_SYNONYMS.concat(Array.isArray(extraGroups) ? extraGroups : []);
    const entries = [];
    const byCompact = new Map();

    for (let g = 0; g < groups.length; g += 1) {
      const rawGroup = groups[g];
      if (!Array.isArray(rawGroup) || rawGroup.length < 2) continue;
      const clean = [];
      const seen = new Set();
      for (let i = 0; i < rawGroup.length; i += 1) {
        const raw = String(rawGroup[i] || "").trim();
        const cmp = compactText(raw);
        if (!cmp || seen.has(cmp)) continue;
        seen.add(cmp);
        clean.push({ raw, norm: normalize(raw), compact: cmp, isCjk: hasCjk(raw), py: toPinyin(raw) });
      }
      if (clean.length < 2) continue;
      const groupObj = { terms: clean };
      entries.push(groupObj);
      for (let i = 0; i < clean.length; i += 1) {
        const key = clean[i].compact;
        const list = byCompact.get(key) || [];
        list.push({ group: groupObj, cue: clean[i] });
        byCompact.set(key, list);
      }
    }

    return { groups: entries, byCompact };
  }

  function expandQuerySynonyms(synIndex, rawToken) {
    const qCompact = compactText(rawToken);
    if (!qCompact || qCompact.length < 2) return [];
    const matchedGroups = [];
    const seenGroup = new Set();
    const isAscii = /^[a-z0-9]+$/.test(qCompact);

    // 1) 精确命中同义词表
    const direct = synIndex.byCompact.get(qCompact);
    if (direct) {
      for (let i = 0; i < direct.length; i += 1) {
        if (!seenGroup.has(direct[i].group)) {
          seenGroup.add(direct[i].group);
          matchedGroups.push({ group: direct[i].group, cue: direct[i].cue.raw, strength: 1 });
        }
      }
    }

    // 2) 前缀 / 中文意群子串 / 拼音命中同义词表
    for (let g = 0; g < synIndex.groups.length; g += 1) {
      const grp = synIndex.groups[g];
      if (seenGroup.has(grp)) continue;
      for (let i = 0; i < grp.terms.length; i += 1) {
        const t = grp.terms[i];
        let matched = false;
        let strength = 0.85;
        if (t.compact.length >= 2 && qCompact.length >= 2) {
          if (t.compact.startsWith(qCompact) && (t.isCjk || qCompact.length >= 3)) {
            matched = true;
            strength = 0.92;
          } else if (qCompact.includes(t.compact) && t.compact.length >= (t.isCjk ? 2 : 4)) {
            matched = true;
            strength = 0.86;
          } else if (t.isCjk && qCompact.length >= 2 && t.compact.includes(qCompact)) {
            matched = true;
            strength = 0.84;
          } else if (isAscii && qCompact.length >= 3 && t.isCjk) {
            if (
              t.py.initialsList.some((ini) => ini === qCompact || (qCompact.length >= 3 && ini.startsWith(qCompact))) ||
              t.py.fulls.some((pf) => pf === qCompact || (qCompact.length >= 4 && pf.startsWith(qCompact)))
            ) {
              matched = true;
              strength = 0.82;
            }
          } else if (t.isCjk && qCompact.length >= 3 && Math.abs(t.compact.length - qCompact.length) <= 1) {
            // 同义词 1 字错字容错（如「向良精度」→「向量精度」→「向量存储精度」）
            if (editDistance(qCompact, t.compact, 1) <= 1) {
              matched = true;
              strength = 0.76;
            }
          }
        }
        if (matched) {
          seenGroup.add(grp);
          matchedGroups.push({ group: grp, cue: t.raw, strength });
          break;
        }
      }
    }

    const expansions = [];
    const seenTerm = new Set([qCompact]);
    for (let i = 0; i < matchedGroups.length; i += 1) {
      const mg = matchedGroups[i];
      for (let j = 0; j < mg.group.terms.length; j += 1) {
        const t = mg.group.terms[j];
        if (seenTerm.has(t.compact)) continue;
        seenTerm.add(t.compact);
        expansions.push({ term: t, cue: mg.cue, strength: mg.strength });
      }
    }
    return expansions;
  }

  function prepare(items, options) {
    const opts = options || {};
    const getTitle = opts.getTitle || ((item) => item && item.title);
    const getDesc = opts.getDesc || ((item) => item && item.desc);
    const getKey = opts.getKey || ((item) => item && item.key);
    const getGroup = opts.getGroup || ((item) => item && item.group);
    const getAliases = opts.getAliases || ((item) => (item && item.aliases) || []);
    const getPriority = opts.getPriority || ((item) => (item && item.priority) || 0);

    const list = Array.isArray(items) ? items : [];
    const compiled = new Array(list.length);

    for (let i = 0; i < list.length; i += 1) {
      const item = list[i];
      const title = String(getTitle(item) ?? "");
      const desc = String(getDesc(item) ?? "");
      const key = String(getKey(item) ?? "");
      const group = String(getGroup(item) ?? "");
      const rawAliases = getAliases(item);
      const aliasArr = Array.isArray(rawAliases) ? rawAliases : [];

      const aliases = [];
      for (let j = 0; j < aliasArr.length; j += 1) {
        const raw = String(aliasArr[j] ?? "").trim();
        if (!raw) continue;
        aliases.push({
          raw,
          norm: normalize(raw),
          compact: compactText(raw),
          py: toPinyin(raw),
          bigrams: bigrams(raw),
        });
      }

      const titleNorm = normalize(title);
      const titleCompact = compactText(title);
      const groupNorm = normalize(group);
      const groupCompact = compactText(group);
      const keyNorm = normalize(key);
      const keyCompact = compactText(key);
      const keyWords = splitKeyWords(key);
      const descNorm = normalize(desc);
      const descCompact = compactText(desc);

      const titlePy = toPinyin(title);
      const groupPy = toPinyin(group);
      const combinedPy = toPinyin(group + " " + title);

      const titleBigrams = bigrams(title);
      const groupBigrams = bigrams(group);
      const descBigrams = bigrams(desc);

      compiled[i] = {
        index: i,
        item,
        priority: Number(getPriority(item)) || 0,
        title,
        titleNorm,
        titleCompact,
        group,
        groupNorm,
        groupCompact,
        key,
        keyNorm,
        keyCompact,
        keyWords,
        desc,
        descNorm,
        descCompact,
        aliases,
        titlePy,
        groupPy,
        combinedPy,
        titleBigrams,
        groupBigrams,
        descBigrams,
      };
    }

    return {
      entries: compiled,
      synIndex: buildSynonymIndex(opts.synonyms),
    };
  }

  function scoreDirectLayer(entry, qNorm, qCompact, termsOut) {
    if (!qNorm || !qCompact) return { score: 0, hit: false };
    let score = 0;
    let titleHit = false;
    let groupHit = false;
    let bestHit = false;

    if (entry.titleNorm === qNorm || entry.titleCompact === qCompact) {
      score = Math.max(score, 1200);
      termsOut.add(entry.title);
      titleHit = true;
      bestHit = true;
    } else if (entry.keyNorm === qNorm || (qCompact.length >= 4 && entry.keyCompact === qCompact)) {
      score = Math.max(score, 1150);
      termsOut.add(entry.key);
      bestHit = true;
    } else if (entry.titleNorm.startsWith(qNorm) || entry.titleCompact.startsWith(qCompact)) {
      score = Math.max(score, 860 + Math.round((qCompact.length / Math.max(1, entry.titleCompact.length)) * 80));
      termsOut.add(qNorm);
      titleHit = true;
      bestHit = true;
    } else if (
      entry.keyNorm.startsWith(qNorm) ||
      (qCompact.length >= 4 && entry.keyCompact.startsWith(qCompact)) ||
      entry.keyWords.some((w) => w === qCompact || (qCompact.length >= 3 && w.startsWith(qCompact)))
    ) {
      score = Math.max(score, 820);
      termsOut.add(qNorm);
      bestHit = true;
    } else if (entry.titleNorm.includes(qNorm) || (qCompact.length >= 2 && entry.titleCompact.includes(qCompact))) {
      score = Math.max(score, 680 + Math.round((qCompact.length / Math.max(1, entry.titleCompact.length)) * 90));
      termsOut.add(qNorm);
      titleHit = true;
      bestHit = true;
    } else if (entry.keyNorm.includes(qNorm) || (qCompact.length >= 4 && entry.keyCompact.includes(qCompact))) {
      score = Math.max(score, 610);
      termsOut.add(qNorm);
      bestHit = true;
    }

    if (entry.groupNorm === qNorm || entry.groupCompact === qCompact) {
      score = Math.max(score, 740);
      termsOut.add(entry.group);
      groupHit = true;
      bestHit = true;
    } else if (entry.groupNorm.startsWith(qNorm) || entry.groupCompact.startsWith(qCompact)) {
      score = Math.max(score, 540);
      termsOut.add(qNorm);
      groupHit = true;
      bestHit = true;
    } else if (entry.groupNorm.includes(qNorm) || (qCompact.length >= 2 && entry.groupCompact.includes(qCompact))) {
      score = Math.max(score, 430);
      termsOut.add(qNorm);
      groupHit = true;
      bestHit = true;
    }

    if (titleHit && groupHit) {
      score += 90;
    }

    for (let i = 0; i < entry.aliases.length; i += 1) {
      const a = entry.aliases[i];
      if (a.compact === qCompact) {
        score = Math.max(score, 940);
        termsOut.add(qNorm);
        bestHit = true;
      } else if (a.compact.startsWith(qCompact) && qCompact.length >= 3) {
        score = Math.max(score, 680);
        termsOut.add(qNorm);
        bestHit = true;
      } else if (a.compact.includes(qCompact) && (hasCjk(qCompact) ? qCompact.length >= 2 : qCompact.length >= 4)) {
        score = Math.max(score, 520);
        termsOut.add(qNorm);
        bestHit = true;
      }
    }

    if (entry.descNorm.includes(qNorm) || (qCompact.length >= 3 && entry.descCompact.includes(qCompact))) {
      score = Math.max(score, 320);
      termsOut.add(qNorm);
      bestHit = true;
    }

    return { score, hit: bestHit };
  }

  function scoreBigramLayer(entry, qCompact, termsOut) {
    const qBigrams = bigrams(qCompact);
    if (!qBigrams.size) return 0;

    let titleHits = 0;
    let groupHits = 0;
    let aliasHits = 0;
    let descHits = 0;
    const matched = [];

    qBigrams.forEach((bg) => {
      let any = false;
      if (entry.titleBigrams.has(bg)) {
        titleHits += 1;
        any = true;
      }
      if (entry.groupBigrams.has(bg)) {
        groupHits += 1;
        any = true;
      }
      for (let i = 0; i < entry.aliases.length; i += 1) {
        if (entry.aliases[i].bigrams.has(bg)) {
          aliasHits += 1;
          any = true;
          break;
        }
      }
      if (entry.descBigrams.has(bg)) {
        descHits += 1;
        any = true;
      }
      if (any) matched.push(bg);
    });

    if (!matched.length) return 0;
    const coverage = matched.length / qBigrams.size;
    const strongHits = Math.max(titleHits, groupHits, aliasHits);

    if (coverage < 0.45 && strongHits < 2) return 0;

    for (let i = 0; i < matched.length; i += 1) termsOut.add(matched[i]);
    const weighted =
      (titleHits * 1.4 + aliasHits * 1.15 + groupHits * 1.0 + descHits * 0.55) /
      Math.max(1, qBigrams.size);
    return Math.round(170 + Math.min(260, weighted * 220 + coverage * 70));
  }

  function scoreSynonymLayer(entry, expansions, termsOut) {
    if (!expansions || !expansions.length) return null;
    let bestScore = 0;
    let bestCue = "";
    const matchedTargets = [];

    for (let i = 0; i < expansions.length; i += 1) {
      const exp = expansions[i];
      const t = exp.term;
      let s = 0;
      if (entry.titleCompact === t.compact || entry.keyCompact === t.compact) {
        s = 560;
        matchedTargets.push(t.raw);
      } else if (entry.titleCompact.includes(t.compact) || entry.keyCompact.includes(t.compact)) {
        s = 490;
        matchedTargets.push(t.raw);
      } else if (entry.aliases.some((a) => a.compact === t.compact || a.compact.includes(t.compact))) {
        s = 470;
        matchedTargets.push(t.raw);
      } else if (entry.groupCompact === t.compact || entry.groupCompact.includes(t.compact)) {
        s = 370;
        matchedTargets.push(t.raw);
      } else if (t.compact.length >= 2 && entry.descCompact.includes(t.compact)) {
        s = 270;
        matchedTargets.push(t.raw);
      }
      s = Math.round(s * exp.strength);
      if (s > bestScore) {
        bestScore = s;
        bestCue = exp.cue;
      }
    }

    if (bestScore <= 0) return null;
    for (let i = 0; i < matchedTargets.length; i += 1) termsOut.add(matchedTargets[i]);
    return { score: bestScore, cue: bestCue };
  }

  function matchSinglePinyin(pyInfo, qAscii, baseScore, termsOut) {
    if (!pyInfo || !pyInfo.full) return 0;
    let best = 0;

    // 1) 首字母精确 / 前缀 / 子串
    for (let i = 0; i < pyInfo.initialsList.length; i += 1) {
      const ini = pyInfo.initialsList[i];
      if (!ini) continue;
      if (ini === qAscii) {
        best = Math.max(best, baseScore + 150);
        const span = mapInitialSpanToSource(pyInfo, 0, ini.length);
        if (span) termsOut.add(span);
      } else if (ini.startsWith(qAscii)) {
        best = Math.max(best, baseScore + 85);
        const span = mapInitialSpanToSource(pyInfo, 0, qAscii.length);
        if (span) termsOut.add(span);
      } else if (qAscii.length >= 2) {
        const pos = ini.indexOf(qAscii);
        if (pos >= 0) {
          best = Math.max(best, baseScore + 30);
          const span = mapInitialSpanToSource(pyInfo, pos, qAscii.length);
          if (span) termsOut.add(span);
        } else if (qAscii.length >= 3 && qAscii.length <= 8) {
          // 紧缩首字母子序列（如 xljd -> xlccjd「向量存储精度」）
          const sub = tightSubsequence(qAscii, ini);
          if (sub) {
            best = Math.max(best, Math.round(baseScore - 20 + sub.ratio * 45));
            const span = mapInitialSpanToSource(pyInfo, sub.first, sub.span);
            if (span) termsOut.add(span);
          }
        }
      }
    }

    // 2) 全拼精确 / 前缀 / 子串
    for (let i = 0; i < pyInfo.fulls.length; i += 1) {
      const full = pyInfo.fulls[i];
      if (!full) continue;
      const useAlt = i === 1;
      if (full === qAscii) {
        best = Math.max(best, baseScore + 170);
        if (pyInfo.source) termsOut.add(pyInfo.source);
      } else if (qAscii.length >= 2 && full.startsWith(qAscii)) {
        best = Math.max(best, baseScore + 95);
        const span = mapFullPinyinSpanToSource(pyInfo, full, 0, qAscii.length, useAlt);
        if (span) termsOut.add(span);
      } else if (qAscii.length >= 3) {
        const pos = full.indexOf(qAscii);
        if (pos >= 0) {
          best = Math.max(best, baseScore + 40);
          const span = mapFullPinyinSpanToSource(pyInfo, full, pos, qAscii.length, useAlt);
          if (span) termsOut.add(span);
        }
      }
    }

    return best;
  }

  function scorePinyinLayer(entry, qCompact, termsOut) {
    if (!/^[a-z]{2,}$/.test(qCompact)) return 0;
    let score = 0;
    score = Math.max(score, matchSinglePinyin(entry.titlePy, qCompact, 420, termsOut));
    score = Math.max(score, matchSinglePinyin(entry.groupPy, qCompact, 340, termsOut));
    score = Math.max(score, matchSinglePinyin(entry.combinedPy, qCompact, 360, termsOut));
    for (let i = 0; i < entry.aliases.length; i += 1) {
      score = Math.max(score, matchSinglePinyin(entry.aliases[i].py, qCompact, 350, termsOut));
    }
    return score;
  }

  function scoreFuzzyLayer(entry, qCompact, termsOut) {
    const qLen = qCompact.length;
    if (qLen < 2) return 0;
    const isCjkQuery = hasCjk(qCompact);
    const isAsciiQuery = /^[a-z0-9]+$/.test(qCompact);
    let score = 0;

    // 1) Damerau-Levenshtein 1 字容错（英文单词 / 拼音全拼均支持 1 字错字）
    if ((isCjkQuery && qLen >= 3) || (isAsciiQuery && qLen >= 4)) {
      const maxDist = 1;
      const titleFuzzy = findFuzzySubstring(qCompact, entry.titleCompact, maxDist);
      if (titleFuzzy) {
        score = Math.max(score, 320 - titleFuzzy.dist * 55);
        if (titleFuzzy.slice) termsOut.add(titleFuzzy.slice);
      }
      const groupFuzzy = findFuzzySubstring(qCompact, entry.groupCompact, maxDist);
      if (groupFuzzy) {
        score = Math.max(score, 260 - groupFuzzy.dist * 45);
        if (groupFuzzy.slice) termsOut.add(groupFuzzy.slice);
      }
      if (isAsciiQuery) {
        for (let i = 0; i < entry.keyWords.length; i += 1) {
          const w = entry.keyWords[i];
          if (w.length < 3) continue;
          const d = editDistance(qCompact, w, maxDist);
          if (d <= maxDist) {
            score = Math.max(score, 310 - d * 55);
            termsOut.add(w);
          }
        }
        // 英文拼音 1 字打错容错（如 shuaidian -> shuaijian「衰减」）
        if (qLen >= 5) {
          const pyFuzzyTitle = findFuzzySubstring(qCompact, entry.titlePy.full, 1);
          if (pyFuzzyTitle) {
            score = Math.max(score, 275 - pyFuzzyTitle.dist * 50);
          }
          const pyFuzzyGroup = findFuzzySubstring(qCompact, entry.groupPy.full, 1);
          if (pyFuzzyGroup) {
            score = Math.max(score, 235 - pyFuzzyGroup.dist * 45);
          }
        }
      }
      for (let i = 0; i < entry.aliases.length; i += 1) {
        const aFuzzy = findFuzzySubstring(qCompact, entry.aliases[i].compact, maxDist);
        if (aFuzzy) {
          score = Math.max(score, 270 - aFuzzy.dist * 50);
          if (aFuzzy.slice) termsOut.add(aFuzzy.slice);
        }
      }
    }

    // 2) 中文紧凑有序子序列（例如「向量精」命中「向量存储精度」）
    if (isCjkQuery && qLen >= 2) {
      const titleSub = tightSubsequence(qCompact, entry.titleCompact);
      if (titleSub) {
        score = Math.max(score, Math.round(230 + titleSub.ratio * 95));
        for (let i = 0; i < titleSub.chars.length; i += 1) termsOut.add(titleSub.chars[i]);
      }
      const groupSub = tightSubsequence(qCompact, entry.groupCompact);
      if (groupSub) {
        score = Math.max(score, Math.round(180 + groupSub.ratio * 75));
        for (let i = 0; i < groupSub.chars.length; i += 1) termsOut.add(groupSub.chars[i]);
      }
    }

    return score;
  }

  function scoreSingleToken(entry, rawToken, synIndex, termsOut) {
    const qNorm = normalize(rawToken);
    const qCompact = compactText(rawToken);
    if (!qCompact) return { score: 0, matchKind: "", reason: "", matchedAlias: "" };

    const direct = scoreDirectLayer(entry, qNorm, qCompact, termsOut);
    const bigramScore = direct.score < 660 ? scoreBigramLayer(entry, qCompact, termsOut) : 0;
    const expansions = expandQuerySynonyms(synIndex, rawToken);
    const synHit = scoreSynonymLayer(entry, expansions, termsOut);
    const pyScore = scorePinyinLayer(entry, qCompact, termsOut);
    const fuzzyScore = direct.score === 0 && pyScore === 0 ? scoreFuzzyLayer(entry, qCompact, termsOut) : 0;

    let bestScore = direct.score;
    let matchKind = direct.score > 0 ? "exact" : "";
    let reason = "";
    let matchedAlias = "";

    if (synHit && synHit.score > bestScore) {
      bestScore = synHit.score;
      matchKind = "alias";
      matchedAlias = synHit.cue;
      reason = "别名：" + synHit.cue;
    } else if (synHit && direct.score > 0) {
      // 同义词同时命中给予平滑加权
      bestScore += Math.round(synHit.score * 0.16);
    }

    if (pyScore > bestScore) {
      bestScore = pyScore;
      matchKind = "pinyin";
      reason = "拼音匹配";
      matchedAlias = "";
    }

    if (bigramScore > bestScore) {
      bestScore = bigramScore;
      matchKind = "bigram";
      reason = "语义切词";
      matchedAlias = "";
    }

    if (fuzzyScore > bestScore) {
      bestScore = fuzzyScore;
      matchKind = "fuzzy";
      reason = "容错匹配";
      matchedAlias = "";
    }

    return { score: bestScore, matchKind, reason, matchedAlias };
  }

  function search(index, rawQuery, options) {
    if (!index || !Array.isArray(index.entries)) return [];
    const opts = options || {};
    const limit = Number.isFinite(opts.limit) ? Math.max(1, opts.limit) : 40;
    const minScore = Number.isFinite(opts.minScore) ? opts.minScore : 1;

    const qNorm = normalize(rawQuery);
    const qCompact = compactText(qNorm);
    if (!qNorm || !qCompact) return [];
    const qTokens = qNorm.split(/\s+/).filter((t) => compactText(t).length > 0);
    const synIndex = index.synIndex;
    const results = [];

    // 预计算整句与各词元的同义词展开，避免对 300 条重复查表
    const wholeExpansions = expandQuerySynonyms(synIndex, qNorm);
    const tokenExpansions = qTokens.length > 1 ? qTokens.map((t) => expandQuerySynonyms(synIndex, t)) : null;

    const entries = index.entries;
    for (let i = 0; i < entries.length; i += 1) {
      const entry = entries[i];
      const termsOut = new Set();

      // 整句评估
      const direct = scoreDirectLayer(entry, qNorm, qCompact, termsOut);
      const bigramScore = direct.score < 660 ? scoreBigramLayer(entry, qCompact, termsOut) : 0;
      const synHit = scoreSynonymLayer(entry, wholeExpansions, termsOut);
      const pyScore = scorePinyinLayer(entry, qCompact, termsOut);
      const fuzzyScore = direct.score === 0 && pyScore === 0 ? scoreFuzzyLayer(entry, qCompact, termsOut) : 0;

      let score = direct.score;
      let matchKind = direct.score > 0 ? "exact" : "";
      let reason = "";
      let matchedAlias = "";

      if (synHit && synHit.score > score) {
        score = synHit.score;
        matchKind = "alias";
        matchedAlias = synHit.cue;
        reason = "别名：" + synHit.cue;
      } else if (synHit && score > 0) {
        score += Math.round(synHit.score * 0.16);
      }

      if (pyScore > score) {
        score = pyScore;
        matchKind = "pinyin";
        reason = "拼音匹配";
        matchedAlias = "";
      }

      if (bigramScore > score) {
        score = bigramScore;
        matchKind = "bigram";
        reason = "语义切词";
        matchedAlias = "";
      }

      if (fuzzyScore > score) {
        score = fuzzyScore;
        matchKind = "fuzzy";
        reason = "容错匹配";
        matchedAlias = "";
      }

      // 多词联合评分（例如「检索 精度」「群聊 衔接」「float16 向量」）
      if (qTokens.length > 1) {
        let hitCount = 0;
        let tokenSum = 0;
        let tokenKind = "";
        let tokenReason = "";
        let tokenAlias = "";
        for (let t = 0; t < qTokens.length; t += 1) {
          const tok = qTokens[t];
          const tokCompact = compactText(tok);
          if (!tokCompact) continue;
          const tDirect = scoreDirectLayer(entry, tok, tokCompact, termsOut);
          const tSyn = scoreSynonymLayer(entry, tokenExpansions[t], termsOut);
          const tPy = scorePinyinLayer(entry, tokCompact, termsOut);
          const tBigram = tDirect.score < 500 ? scoreBigramLayer(entry, tokCompact, termsOut) : 0;
          const tFuzzy = tDirect.score === 0 && tPy === 0 ? scoreFuzzyLayer(entry, tokCompact, termsOut) : 0;

          let ts = tDirect.score;
          let tk = tDirect.score > 0 ? "exact" : "";
          let tr = "";
          let ta = "";
          if (tSyn && tSyn.score > ts) {
            ts = tSyn.score;
            tk = "alias";
            ta = tSyn.cue;
            tr = "别名：" + tSyn.cue;
          }
          if (tPy > ts) {
            ts = tPy;
            tk = "pinyin";
            tr = "拼音匹配";
            ta = "";
          }
          if (tBigram > ts) {
            ts = tBigram;
            tk = "bigram";
            tr = "语义切词";
            ta = "";
          }
          if (tFuzzy > ts) {
            ts = tFuzzy;
            tk = "fuzzy";
            tr = "容错匹配";
            ta = "";
          }

          if (ts > 0) {
            hitCount += 1;
            tokenSum += ts;
            if (!tokenKind || tk === "alias" || tk === "pinyin") {
              tokenKind = tk;
              tokenReason = tr;
              tokenAlias = ta;
            }
          }
        }

        if (hitCount > 0) {
          const avg = Math.round(tokenSum / qTokens.length);
          const allHit = hitCount === qTokens.length;
          const multiScore = allHit ? avg + 340 : hitCount / qTokens.length >= 0.5 ? Math.round(avg * 0.72) : 0;
          if (multiScore > score) {
            score = multiScore;
            matchKind = tokenKind || "exact";
            reason = tokenReason;
            matchedAlias = tokenAlias;
          }
        }
      }

      if (score >= minScore) {
        results.push({
          item: entry.item,
          score: score + entry.priority,
          rawScore: score,
          matchKind: matchKind || "exact",
          reason,
          matchedAlias,
          matchedTerms: Array.from(termsOut).filter(Boolean),
          _order: entry.index,
        });
      }
    }

    results.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      if (b.rawScore !== a.rawScore) return b.rawScore - a.rawScore;
      return a._order - b._order;
    });

    return results.slice(0, limit).map((r) => ({
      item: r.item,
      score: r.score,
      matchKind: r.matchKind,
      reason: r.reason,
      matchedAlias: r.matchedAlias,
      matchedTerms: r.matchedTerms,
    }));
  }

  function highlight(text, matchedTerms, options) {
    const raw = String(text ?? "");
    if (!raw) return "";
    const terms = Array.isArray(matchedTerms) ? matchedTerms : [];
    if (!terms.length) return escapeHtml(raw);

    const markClass = (options && options.markClass) || "cfg-search-mark";
    const lower = raw.toLowerCase();
    const cleaned = [];
    const seen = new Set();

    for (let i = 0; i < terms.length; i += 1) {
      const t = String(terms[i] ?? "").trim().toLowerCase();
      if (!t || seen.has(t)) continue;
      seen.add(t);
      cleaned.push(t);
    }
    if (!cleaned.length) return escapeHtml(raw);

    // 较长匹配词优先，避免单字拆碎整词高亮
    cleaned.sort((a, b) => b.length - a.length);

    const ranges = [];
    for (let i = 0; i < cleaned.length; i += 1) {
      const term = cleaned[i];
      // 若已有 >=2 字词命中文本，则跳过单字噪音高亮
      if (term.length === 1 && ranges.length > 0) continue;
      let pos = 0;
      while (pos < lower.length) {
        const found = lower.indexOf(term, pos);
        if (found < 0) break;
        ranges.push([found, found + term.length]);
        pos = found + term.length;
      }
    }

    if (!ranges.length) return escapeHtml(raw);
    ranges.sort((a, b) => a[0] - b[0] || b[1] - a[1]);

    const merged = [ranges[0].slice()];
    for (let i = 1; i < ranges.length; i += 1) {
      const prev = merged[merged.length - 1];
      const cur = ranges[i];
      if (cur[0] <= prev[1]) {
        if (cur[1] > prev[1]) prev[1] = cur[1];
      } else {
        merged.push(cur.slice());
      }
    }

    let out = "";
    let cursor = 0;
    const openTag = '<mark class="' + escapeHtml(markClass) + '">';
    for (let i = 0; i < merged.length; i += 1) {
      const start = merged[i][0];
      const end = merged[i][1];
      if (start > cursor) out += escapeHtml(raw.slice(cursor, start));
      out += openTag + escapeHtml(raw.slice(start, end)) + "</mark>";
      cursor = end;
    }
    if (cursor < raw.length) out += escapeHtml(raw.slice(cursor));
    return out;
  }

  return {
    DEFAULT_SYNONYMS,
    escapeHtml,
    normalize,
    compactText,
    bigrams,
    toPinyin,
    editDistance,
    prepare,
    search,
    highlight,
  };
});
