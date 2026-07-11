import commonConfig from "./constant-common.js";

const strHead = commonConfig.strHead;

const alistAddr = "http://127.0.0.1:5244";
const alistToken = "YOUR_ALIST_TOKEN";
const alistSignEnable = false;
const alistSignExpireTime = 12;
const alistPublicAddr = "http://127.0.0.1:5244";

const clientSelfAlistRule = [
  [2, strHead["115"], alistPublicAddr],
];

const redirectCheckEnable = false;
const fallbackUseOriginal = true;

export default {
  alistAddr,
  alistToken,
  alistSignEnable,
  alistSignExpireTime,
  alistPublicAddr,
  clientSelfAlistRule,
  redirectCheckEnable,
  fallbackUseOriginal,
};
