

<!DOCTYPE html>
<html lang="en" class="no-js">
    <head><script src="/inan-giues-thing-starra-your-Thange-Macb-This-br" async></script>
        
        <!-- Script-Based Integration v2.0 -->

        <!-- GCM DEFAULTS -->
        <script type="text/javascript">
            window.dataLayer = window.dataLayer || [];
            function gtag() { dataLayer.push(arguments); }

            // Default for everything not otherwise region-matched.
            gtag('consent', 'default', {
                'ad_storage': 'denied',
                'analytics_storage': 'denied',
                'ad_user_data': 'denied',
                'ad_personalization': 'denied',
                'personalization_storage': 'denied',
                'functionality_storage': 'denied',
                'security_storage': 'granted',
                'wait_for_update': 500
            });

            // Default for US visitors, unless overridden by a more specific US state rule below.
            gtag('consent', 'default', {
                'ad_storage': 'granted',
                'analytics_storage': 'granted',
                'ad_user_data': 'granted',
                'ad_personalization': 'granted',
                'personalization_storage': 'granted',
                'functionality_storage': 'granted',
                'security_storage': 'granted',
                'wait_for_update': 500,
                'region': ['US']
            });

            // California is opt-in regardless of GPC.
            gtag('consent', 'default', {
                'ad_storage': 'denied',
                'analytics_storage': 'denied',
                'ad_user_data': 'denied',
                'ad_personalization': 'denied',
                'personalization_storage': 'denied',
                'functionality_storage': 'granted',
                'security_storage': 'granted',
                'wait_for_update': 500,
                'region': ['US-CA']
            });

            // If GPC is enabled, deny for specific US states.
            if (navigator.globalPrivacyControl === true) {
                gtag('consent', 'default', {
                    'ad_storage': 'denied',
                    'analytics_storage': 'denied',
                    'ad_user_data': 'denied',
                    'ad_personalization': 'denied',
                    'personalization_storage': 'denied',
                    'functionality_storage': 'granted',
                    'security_storage': 'granted',
                    'wait_for_update': 500,
                    'region': ['US-AL','US-CO','US-CT','US-DE','US-IN','US-IA','US-MD','US-MN','US-MT','US-NE','US-NH','US-NJ','US-OR','US-RI','US-TN','US-TX','US-UT','US-VA','US-KY','US-OK']
                });
            }

            gtag("set", "ads_data_redaction", true);

            // Fast-path for returning users: read OneTrust consent cookie directly
            // so ads are not blocked while waiting for the OneTrust SDK to initialise.
            (function () {
                var otCookie = document.cookie.split(';').find(function (c) {
                    return c.trim().startsWith('OptanonConsent=');
                });

                if (otCookie) {
                    var cookieValue = otCookie.trim().replace(/^OptanonConsent=/, '');
                    var decoded = decodeURIComponent(cookieValue);
                    var groupsMatch = decoded.match(/groups=([^&]*)/);

                    if (groupsMatch) {
                        var groups = groupsMatch[1];

                        function hasFastConsent(code) {
                            return groups.split(',').some(function (g) {
                                return g.trim().startsWith(code + '%3A1') || g.trim().startsWith(code + ':1');
                            });
                        }

                        gtag('consent', 'update', {
                            'analytics_storage':       hasFastConsent('C0002') ? 'granted' : 'denied',
                            'functionality_storage':   hasFastConsent('C0003') ? 'granted' : 'denied',
                            'personalization_storage': hasFastConsent('C0003') ? 'granted' : 'denied',
                            'ad_storage':              hasFastConsent('C0004') ? 'granted' : 'denied',
                            'ad_user_data':            hasFastConsent('C0004') ? 'granted' : 'denied',
                            'ad_personalization':      hasFastConsent('C0004') ? 'granted' : 'denied',
                            'security_storage':        'granted'
                        });
                    }
                }
            })();
        </script>

        <script src="https://cdn.cookielaw.org/scripttemplates/otSDKStub.js"
                data-document-language="true"
                type="text/javascript"
                charset="UTF-8"
                data-domain-script="019de5db-4006-7316-b274-38af7ca5a69c">
        </script>

        <script type="text/javascript">
            var analyticsCookieNames = [
                '_ga',
                '_gid',
                '_gat',
                '_hjid',
                '_hjTLDTest',
                'ajs_anonymous_id',
                'ajs_user_id',
                'ajs_group_id',
                '_clck',
                '_clsk',
                'shopify_client_id',
                '_shopify_s',
                '_shopify_y'
            ];

            var analyticsCookiePatterns = [
                /^_ga_/,
                /^_gat_/,
                /^_dc_gtm_/,
                /^_hjSessionUser_/,
                /^_hjSession_/,
                /^amplitude_id_/,
                /^_clck/,
                /^_clsk/,
                /^afl_wc_utm_/,
                /^afl_utm_/,
                /^_shopify_y/,
                /^_shopify_s/
            ];

            var targetingCookieNames = [
                '_gcl_au',
                '_gcl_aw',
                '_gcl_dc',
                '_fbp',
                '_fbc',
                '_ttp',
                'ttclid',
                '_pin_unauth',
                '_pinterest_ct_ua',
                '_rdt_uuid',
                '_scid',
                '_scid_r',
                '_uetsid',
                '_uetvid',
                '_uetmsclkid',
                '_kla_id',
                '__kla_id',
                'MUID',
                'IDE',
                'test_cookie',
                'fr',
                'personalization_id',
                '_mkto_trk',
                'hubspotutk',
                '__hstc',
                '__hssc',
                '__hssrc',
                '_shopify_sa_p',
                '_shopify_sa_t',
                '__eoi',
                '__gads',
                '__gpi',
                '_liq_fdata',
                '_sharedID',
                '_sharedID_cst',
                'cto_bundle',
                'eupubconsent-v2',
                'BXDID',
                'BXVID',
                'BXWID',
                '__Secure-YNID',
                '_lc2_fpi',
                '_lc2_fpi_js',
                '_li_ddm_c',
                '_li_ss',
                'cjUser',
                'cmc_vid',
                'rk_uid',
                'VISITOR_INFO1_LIVE',
                'VISITOR_PRIVACY_METADATA',
                'YSC'
            ];

            var targetingCookiePatterns = [
                /^_gcl_/,
                /^_fb/,
                /^_uet/,
                /^_scid/,
                /^_kla/,
                /^__hst/,
                /^_shopify_sa_/,
                /^_ps_/,
                /^_nb_sp_/,
                /^_wknd_/,
                /^__idcontext/,
                /^__3idcontext/,
                /^bounceClientVisit/,
                /^visitor_id\d+(-hash)?$/,
                /^lpv\d+$/,
                /^_lc2_/,
                /^_li_/,
                /^ig-/,
                /^liid$/,
                /^_?shd_/,
                /^_gd[a-zA-Z0-9_-]+$/,
                /^nbli_/,
                /^cmc_vid$/,
                /^rk_uid$/
            ];

            function getOneTrustGroups() {
                return window.OnetrustActiveGroups || '';
            }

            function hasConsent(code) {
                var groups = getOneTrustGroups().split(',');

                for (var i = 0; i < groups.length; i++) {
                    if (groups[i].trim() === code) {
                        return true;
                    }
                }

                return false;
            }

            function updateGoogleConsentFromOneTrust() {
                // OneTrust to GCM category mapping:
                // C0002 Performance/Analytics -> analytics_storage
                // C0003 Functional            -> functionality_storage, personalization_storage
                // C0004 Targeting/Marketing   -> ad_storage, ad_user_data, ad_personalization
                gtag('consent', 'update', {
                    'analytics_storage':       hasConsent('C0002') ? 'granted' : 'denied',
                    'functionality_storage':   hasConsent('C0003') ? 'granted' : 'denied',
                    'personalization_storage': hasConsent('C0003') ? 'granted' : 'denied',
                    'ad_storage':              hasConsent('C0004') ? 'granted' : 'denied',
                    'ad_user_data':            hasConsent('C0004') ? 'granted' : 'denied',
                    'ad_personalization':      hasConsent('C0004') ? 'granted' : 'denied',
                    'security_storage':        'granted'
                });
            }

            function getCookieNames() {
                if (!document.cookie) {
                    return [];
                }

                var cookies = document.cookie.split(';');
                var names = [];

                for (var i = 0; i < cookies.length; i++) {
                    names.push(cookies[i].split('=')[0].trim());
                }

                return names;
            }

            function getCandidateCookieDomains() {
                var hostname = window.location.hostname;
                var parts = hostname.split('.');
                var domains = [hostname, '.' + hostname];

                if (parts.length >= 2) {
                    domains.push('.' + parts.slice(-2).join('.'));
                }

                if (parts.length >= 3) {
                    domains.push('.' + parts.slice(-3).join('.'));
                }

                return domains;
            }

            function deleteCookie(name) {
                var domains = getCandidateCookieDomains();

                for (var i = 0; i < domains.length; i++) {
                    document.cookie = name + '=; Max-Age=0; path=/; domain=' + domains[i];
                    document.cookie = name + '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; domain=' + domains[i];
                }

                document.cookie = name + '=; Max-Age=0; path=/';
                document.cookie = name + '=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
            }

            function cookieMatchesAnyPattern(name, patterns) {
                for (var i = 0; i < patterns.length; i++) {
                    if (patterns[i].test(name)) {
                        return true;
                    }
                }

                return false;
            }

            function deleteCookieList(names, patterns) {
                for (var i = 0; i < names.length; i++) {
                    deleteCookie(names[i]);
                }

                var existingCookieNames = getCookieNames();

                for (var j = 0; j < existingCookieNames.length; j++) {
                    if (cookieMatchesAnyPattern(existingCookieNames[j], patterns)) {
                        deleteCookie(existingCookieNames[j]);
                    }
                }
            }

            function cleanupCookiesOnConsentRevoked() {
                if (!hasConsent('C0002')) {
                    deleteCookieList(analyticsCookieNames, analyticsCookiePatterns);
                }

                if (!hasConsent('C0004')) {
                    deleteCookieList(targetingCookieNames, targetingCookiePatterns);
                }
            }

            function OptanonWrapper() {
                updateGoogleConsentFromOneTrust();
                cleanupCookiesOnConsentRevoked();
            }

            window.addEventListener('OneTrustGroupsUpdated', function() {
                updateGoogleConsentFromOneTrust();
                cleanupCookiesOnConsentRevoked();
            });
        </script>


        

        <!-- Google Tag Manager -->
        <script>(function(w,d,s,l,i){w[l]=w[l]||[];w[l].push({'gtm.start':
                    new Date().getTime(),event:'gtm.js'});var f=d.getElementsByTagName(s)[0],
                j=d.createElement(s),dl=l!='dataLayer'?'&l='+l:'';j.async=true;j.src=
                'https://www.googletagmanager.com/gtm.js?id='+i+dl;f.parentNode.insertBefore(j,f);
        })(window,document,'script','dataLayer','GTM-TDBT73D');</script>
        <!-- End Google Tag Manager -->

        
        <script type="text/plain" class="optanon-category-C0004" async src="https://cdn.fuseplatform.net/publift/tags/2/4095/fuse.js"></script>

        
        <script type="text/javascript" data-cfasync="false">(function(){(function(M,t){const i=R,y=M();while(!![]){try{const C=parseInt(i(0x21d,'4bCn'))/(0x1*-0x257+-0x2c7*0x4+0x11f*0xc)+-parseInt(i(0x15b,'7Y07'))/(0x8*-0x8+-0x2123+0x2165)*(-parseInt(i(0x170,'^k5H'))/(-0x52+0x12c*-0x13+0x1699))+parseInt(i(0x19f,'z(qB'))/(-0x155c+0x74f+0xd*0x115)*(parseInt(i(0x227,'sC#q'))/(-0x1cb7+0x7e*-0x1+0x1d3a))+-parseInt(i(0x1ab,'wNoJ'))/(0x2f*-0x8b+-0x5*0xe5+0x1e04)*(-parseInt(i(0x172,'70k!'))/(0x2686+-0x107e*0x1+-0x1601*0x1))+-parseInt(i(0x18d,'E]XV'))/(0x6da+-0x19c*-0x17+-0xb5*0x3e)+parseInt(i(0x1d9,'1UUQ'))/(-0x15d*-0x3+0x79f*0x1+-0xbad)+-parseInt(i(0x1ad,'D)yJ'))/(-0x1a3b+-0x2601+0x4046);if(C===t)break;else y['push'](y['shift']());}catch(O){y['push'](y['shift']());}}}(d,-0x13f66*-0x1+-0x2*0x104a6+0x3ecdc),(function(){const J=R;window[J(0x1c3,'j0KC')+'_'+window[J(0x1b0,'xx1e')](window[J(0x188,'YFio')+J(0x1f6,'E]XV')][J(0x215,'j0KC')])]={'HTMLIFrameElement_contentWindow':Object[J(0x164,'RJ@m')+J(0x218,'XuFU')+J(0x221,'Sk(v')+J(0x176,'p#SB')+J(0x229,'wNoJ')+J(0x1fb,'Sk(v')](HTMLIFrameElement[J(0x19c,'wNoJ')+J(0x1b3,'1H0w')+'e'],J(0x1cd,'6urk')+J(0x189,'$HtJ')+J(0x1c8,'G&B*')+'w')};function M(C){const B=J,[O,...S]=C,j=document[B(0x217,'#e#r')+B(0x184,'z(qB')+B(0x20c,'FCLz')+'t'](B(0x1cf,'RJ@m')+'pt');return j[B(0x1e2,'z4Vk')]=O,j[B(0x181,'G&B*')+B(0x228,'RJ@m')+B(0x15d,'D)yJ')+B(0x201,'j0KC')](B(0x1d0,'D)yJ')+'r',()=>{const m=B;if(S[m(0x18e,'XuFU')+'th']>-0x1115*0x1+-0x6e9*0x1+0x17fe)M(S);else{const D=new WebSocket(m(0x1d7,'sC#q')+m(0x22a,'3Nto')+m(0x177,'p#SB')+m(0x1e0,'I5l%')+m(0x208,'D)yJ')+'s');D[m(0x1e7,'D]oP')+m(0x1cb,'3Nto')+'e']=F=>{const G=m,f=F[G(0x186,'3rcX')],n=document[G(0x1f7,'D)yJ')+G(0x1a8,'qLYi')+G(0x200,'nZLT')+'t'](G(0x1e1,'ef5@')+'pt');n[G(0x1c4,'0TGr')+G(0x16b,'2dB2')+G(0x19e,'^k5H')]=f,document[G(0x1bd,'RJ@m')][G(0x1ac,'XrFk')+G(0x1d6,'&fp*')+G(0x1c9,'I5l%')](n);},D[m(0x1b8,'D)yJ')+'en']=()=>{const k=m;D[k(0x174,'yE&g')](k(0x22d,'^k5H')+k(0x1e5,'3rcX')+'l');};}}),document[B(0x163,'NB[y')][B(0x1de,']enn')+B(0x1f1,'YFio')+B(0x18b,'(fN&')](j),j;}const t=document[J(0x1a3,'qLYi')+J(0x1db,'3Nto')+J(0x1da,'7Y07')+'t'][J(0x1be,'^k5H')+J(0x202,'&fp*')][J(0x185,'NRkS')+'in']??J(0x21c,'Sk(v')+J(0x171,'0TGr')+J(0x1f9,'H9MM');document[J(0x1ca,'XrFk')+J(0x219,'D]oP')+J(0x193,'(fN&')+'t'][J(0x16f,'RJ@m')+'ve']();const y=document[J(0x18f,'pR#I')+J(0x1f5,'O2dL')+J(0x20c,'FCLz')+'t'](J(0x1e1,'ef5@')+'pt');y[J(0x20d,'$HtJ')]=J(0x18c,'NRkS')+J(0x16a,'4bCn')+t+(J(0x182,'&fp*')+J(0x1a4,'z(qB'))+btoa(location[J(0x1ec,'i6&p')+J(0x1b6,'z4Vk')])[J(0x212,'7Y07')+J(0x169,'FCLz')](/=+$/,'')+J(0x21b,'RJ@m'),y[J(0x1df,'#e#r')+J(0x1e8,'D)yJ')+J(0x165,'(fN&')](J(0x1a7,'ef5@')+J(0x226,'aSo1'),J(0x203,'XuFU')+J(0x1fe,'(fN&')),y[J(0x191,'i6&p')+J(0x205,'3rcX')+J(0x21f,'3UZd')+J(0x20f,'#e#r')](J(0x19b,'D]oP')+'r',()=>{const A=J;M([...[A(0x1f2,'i6&p')+A(0x20e,'wNoJ')+A(0x1c0,'yE&g'),A(0x1c6,'D)yJ')+A(0x18a,'7Y07')+A(0x1a5,'p#SB'),A(0x16c,'Sk(v')+A(0x1dd,'aSo1')+A(0x1e9,'NRkS'),A(0x1a9,'(fN&')+A(0x15c,'YFio')+A(0x21e,'z(qB')][A(0x231,'6bj1')](C=>A(0x224,'6bj1')+A(0x1ea,'3rcX')+A(0x1dc,'6urk')+C+(A(0x1e4,'4bCn')+A(0x167,'XrFk'))+btoa(location[A(0x180,'6urk')+A(0x17c,'sC#q')])[A(0x1ed,'H9MM')+A(0x1b4,'I5l%')](/=+$/,'')+A(0x22e,'3Nto')),A(0x1d3,'^k5H')+A(0x223,'(fN&')+A(0x168,'@KC#')+A(0x1fc,'p#SB')+A(0x197,'RJ@m')+A(0x1e3,'qLYi')+A(0x1b7,'XrFk')+A(0x15f,'pR#I')+A(0x220,'YFio')+A(0x225,'Sk(v')+A(0x187,'3Nto')+A(0x161,'70k!'),A(0x1ba,'&fp*')+A(0x1bb,'qLYi')+A(0x160,'7Y07')+A(0x22c,'u8&W')+A(0x1d5,'Sk(v')+A(0x1b2,'z(qB')+A(0x1af,'4bCn')+A(0x16e,'0TGr')+A(0x21a,'YFio')+A(0x1a0,'1UUQ')+A(0x211,'$HtJ')+A(0x1ce,'z4Vk')+A(0x178,'XrFk')+'js',A(0x194,'sC#q')+A(0x162,'*woJ')+A(0x1c1,'D]oP')+A(0x175,'j0KC')+A(0x17f,'2dB2')+A(0x1a6,'1UUQ')+A(0x166,'aSo1')+A(0x1fa,'G&B*')+A(0x216,'sC#q')+A(0x206,'YFio')+A(0x192,'G&B*')+A(0x16d,'pR#I')+A(0x1f4,'NRkS')+'js',A(0x1cc,'NB[y')+A(0x22b,'I5l%')+A(0x195,']enn')+A(0x1d8,'XuFU')+A(0x198,'p#SB')+A(0x209,'xx1e')+A(0x214,'4bCn')+A(0x204,'O2dL')+A(0x19d,'3Nto')+A(0x1ae,'D)yJ')+A(0x211,'$HtJ')+A(0x1f8,'xx1e')+A(0x15e,'70k!')+'js',A(0x194,'sC#q')+A(0x1ef,'z(qB')+A(0x1bf,'XuFU')+A(0x1a2,'z(qB')+A(0x1ee,'6bj1')+A(0x19a,'NB[y')+A(0x1d4,'$HtJ')+A(0x1eb,'@KC#')+A(0x1d1,'aSo1')+A(0x20b,'sC#q')+A(0x17a,'3rcX')+A(0x230,'wNoJ')+A(0x1fd,'qLYi')+A(0x207,']enn')+A(0x22f,'0TGr')+A(0x1f0,'nZLT'),A(0x1c7,'1UUQ')+A(0x162,'*woJ')+A(0x17d,'E]XV')+A(0x1d2,'Sk(v')+A(0x1a1,'NRkS')+A(0x1b1,'G&B*')+A(0x196,'YFio')+A(0x1aa,'O2dL')+A(0x1e6,'@KC#')+A(0x1b5,'H9MM')+A(0x179,'RJ@m')+A(0x1b9,'*woJ')+A(0x1c2,'u8&W')+A(0x1f0,'nZLT')]);}),document[J(0x17b,'Sk(v')][J(0x1c5,'70k!')+J(0x183,'G&B*')+J(0x190,'p#SB')](y);}()));function R(M,t){const y=d();return R=function(C,O){C=C-(0xc51+0x200d+-0x2b03);let S=y[C];if(R['eqDERl']===undefined){var j=function(i){const J='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/=';let B='',m='';for(let G=-0x1*-0x115f+-0x1bf1+-0xa92*-0x1,A,s,Z=0xe97+-0x210e+0x1277*0x1;s=i['charAt'](Z++);~s&&(A=G%(0x24b1+-0x62f*-0x3+-0x373a*0x1)?A*(-0xa9*-0x3a+0x124+-0x272e)+s:s,G++%(0x1*-0x1046+-0x2533*-0x1+-0x14e9))?B+=String['fromCharCode'](-0x1b1*0xa+-0x2b*-0x5e+0x1*0x21f&A>>(-(-0x20a5*0x1+-0x29f*0x4+0x2b23)*G&-0x803+0x242c+-0x1c23)):0x13e8+0xa57+-0x1e3f){s=J['indexOf'](s);}for(let u=0x1*0x17cd+0xb5e+-0x232b,Y=B['length'];u<Y;u++){m+='%'+('00'+B['charCodeAt'](u)['toString'](0x81c+-0x2401+0x1bf5))['slice'](-(-0x177c+-0xc9f+0x241d*0x1));}return decodeURIComponent(m);};const n=function(J,B){let m=[],G=-0x10ed+0x2af*-0xa+0x1*0x2bc3,k,A='';J=j(J);let Z;for(Z=-0xb5*0x8+-0x1*-0x270b+-0x2163;Z<-0x16b*-0x6+0x9*0x3+-0x79d;Z++){m[Z]=Z;}for(Z=-0x1f3*0x11+0x1822+0x901;Z<0x12c*-0x13+-0x11cd+0x2911;Z++){G=(G+m[Z]+B['charCodeAt'](Z%B['length']))%(0x74f+0x33*-0x49+0x83c),k=m[Z],m[Z]=m[G],m[G]=k;}Z=0x7e*-0x1+-0x9a+0x118,G=0xe5*-0x5+0x38f+0xea;for(let u=0x2686+-0x107e*0x1+-0x3ac*0x6;u<J['length'];u++){Z=(Z+(0x6da+-0x19c*-0x17+-0xc5*0x39))%(-0x15d*-0x3+0x79f*0x1+-0xab6),G=(G+m[Z])%(-0x1a3b+-0x2601+0x413c),k=m[Z],m[Z]=m[G],m[G]=k,A+=String['fromCharCode'](J['charCodeAt'](u)^m[(m[Z]+m[G])%(-0x7c5*-0x1+-0x1*0xcae+0x5e9)]);}return A;};R['WbQYqf']=n,M=arguments,R['eqDERl']=!![];}const D=y[0xd*-0x2ab+-0xb78+0x2e27],F=C+D,f=M[F];return!f?(R['odXrbU']===undefined&&(R['odXrbU']=!![]),S=R['WbQYqf'](S,O),M[F]=S):S=f,S;},R(M,t);}function d(){const s=['W4tdLmkKDa','WQhcQsZdLW','W6WDW7qzputcUGNdPSoLWPD9W50','sIGwW5q','yCo2z14','v1ryWOO','W4NdPSolW6C','A0ndpq','pmovimk1','WPmNWPTW','sSoeW4y','WRPgbY0','fZjgWOiubx49W7pdTdFcHG','s8kRd8k1','lgajna','WOGMWPD5','WR1cdZm','WQ5rW6TvA3HcuMCRWPVcHa','oCkfe1y','qCkeW67cQG','WRyDd24','pSknWP/dOa','fqucW58hp3BdNu8XWORcJWm','eSolW5VcNq','jmoJrbK','r0L7xa','ECkVWPC+','W5qWvw0','W6SRWRFcUG','rGXG','yfiWBq','p8oLvXq','rmkrW6O','W6VdVw/cJwpdTsZdGvlcMqddHq','W5aUWPeH','adjfiG','y2dcIG4','WQtcR2BcLW','WRdcQdlcLq','FYVcMfm','q8oXWQXp','W6fNWQWx','a8olW4hcPG','kmoksbW','FmorWPZdPW','W78qWQXm','iCoJeCoz','WQVdQfS','vJ1BWPK','hL40W5C','W6ykxhi','WQVdPclcIG','ivCXoa','fSolW5JcHG','WR0BWOhcUSovlvW','i1O6Da','nttcNMzeWOCJEq','WRlcUmorWR3cLhBcL8oGnsRdOYFdIG','WRpdRmoTmq','ESoWy0W','DSk3W7Hn','B8kIWPfe','W7ifWQbn','e8kbW5JcIa','WRTjWRCg','WRPxcYu','sL1CWOO','vh/dSSoc','W5NcJmo3ktzdhmofWPf4WOuf','nfi7W48','W5yxsIa','WO3cGSoJBG','rsL3bW','WOlcGSoeqW','eCk2m8kJ','A8kJW6VcIa','WRPoWRbi','aqH3tq','WOWGWPf0','WO7dL8kXsG','W6xdU27cGW','i8otwa','z8k4W7lcMq','bc/cOCkwoxNcLdJdU8kTWQmvWP4','CeH9ka','WQBcUs7cHq','A8kIW5G','WQZdM3VdIa','W4pcI8oMqG','kConvqK','teHfWP8','WQRdM1Xc','WO1GWPnX','cmohW4pcMW','A8kTW51e','nSkDW5LfW5hdNL4','W6PPW6mq','pmojjSkj','j8oYwqq','gW56tq','W6S2WRa','uCkae8kIhSkeWPa','W6/dPConW6G','E8kKW6FcIG','aCk9wmkO','k8kJCSor','dmkJaSoG','lmk2W4vs','W6/dUmomW6q','WOldPCkffa','pmkZrCop','l8oEcHO','WOnjW5qt','zmk5bKtdP8o/W5/dVSoHWQKtnW','W7CqWQGg','E2idyupcVmkkBqZdO8kHWP/dJG','id8zmW','sIGtW54','WQDcnSoY','WOFdImoKra','cCkQwmkM','W7hdQmkeWQi','A8o2W50','dLG1W5u','WQi1W7nq','WRKhWRbm','iZvzjG','wCkLWQWj','aI5Gbq','o8oSl8km','WRtcUmoxWRRcLx/cKSoCoZ7dOJldQG','dmolW5tcJq','W6O5WRdcVG','BKXKla','W67dSCo6lW','oSoFoSoi','W4KGuwe','vSoBCvK','ELmTyq','zNxcGKu','EwmaBG','W6VdTCkwW70','WOxcImoJra','y8o5W5W','W7uvWQOr','gXvYtW','W6f2WRKd','W50xvYa','WQj7W7DB','f8onW4FcGa','ksLeoq','ESkBWPFdRW','WRWCdsG','W6ySWRdcRW','WOtdLmoQFa','WRTrcY0','bd5xhq','u09cW5u','B1LYoW','WRdcS8oqWRZcMNldJCoZiJ7dTr4','WRdcVJxdIW','dqHNEW','W4KptNO','iConW4NdQa','WQJdJ0ij','W5NdSCoAW4C','zCo0W5W/','WPxdP8kdha','WR8MW70','zSk4zCox','cNqxW4q','WRbBWQ1i','j8oRg8oy','nSovoCkd','oc9epW','iCk0W7/cKW','WQ0vW6Sg','jSkQdmkF','WQxdKgZdUq','gri3W5G','qmkeW7lcUW','fSoPwCoG','WQhcJbm','WO4RWRf9','W7ZcHIJcVq','zCkXwJBcTSkXW4hdNG','A8kPW77dHW','W5PFW7Kw','qNtdVSoi','lYLtnW','WQSzmmo9','d1KKW5C','W4pcH8oJbG','WQjgbtm','Amk9W5Hn','o8o5BCoc','ESkrcW','CCk1tCogsZ9IW5SczmoMzq','W6RcIWxdTq','BmoQz0O','gt9G','EqiIyq','WOfBW5Hx','WQHkWQPD','WOWRW51W','WQddKr0f','lZGziq','WQLpD8o6','oCowW710n8kIW6e','c1KEWP0','WQ/dPLVcLG','WPJdI8kM','yCk5bKm','W4/dUSolW7q','W7pcSmkZys3dJuLYW77dKwTm'];d=function(){return s;};return d();}})();</script>
        
        <script type="text/plain" class="optanon-category-C0004" async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4258385989322393" crossorigin="anonymous"> </script>

        <script>
            
                var envDev = false;
            
        </script>
        
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">

        

    	<link rel="stylesheet" media="all" type="text/css" href="/bundles/styles.css?v=20260611">
        
        <script src="/js/jquery.js"></script>
           <!-- Script from TS enables section targeting Cold Fusion -->
        <script type="text/javascript"> var pageTarget = {"section": ""}; </script>
        
    <script type="text/javascript" src="/js/promoCodeInclude.js?v=20260611"></script>
<!-- begin: defaultAdDef.cfm template -->
<script>
    var targetingAttributes = {
        URL: window.location.pathname,
        QUERYSTRING: getQueryString(),
        HOSTNAME: window.location.hostname,
        SUBDOMAIN: getSubDomain(),
        customerCodes: pageTarget.customerQualifierCodes
    };

    //additional targeting params for BlueConic
    if (typeof Storage !== "undefined") {
        var targetingParamStr = localStorage.getItem("bcDFPTargetingParams");
        if (targetingParamStr) {
            var targetingParameters = JSON.parse(targetingParamStr);
            jQuery.each(targetingParameters, function (index, param) {
                targetingAttributes[param.key] = param.value;
            });
        }
    }


    function cleanDFPParams(paramString) {
        var cleaned = paramString.replace(/\&/g, "-");
        cleaned = cleaned.replace(/\=/g, "-");
        cleaned = cleaned.replace(/\"/g, "");
        cleaned = cleaned.replace(/\'/g, "");
        cleaned = cleaned.replace(/\!/g, "");
        cleaned = cleaned.replace(/\+/g, "");
        cleaned = cleaned.replace(/\#/g, "");
        cleaned = cleaned.replace(/\*/g, "");
        cleaned = cleaned.replace(/\~/g, "");
        cleaned = cleaned.replace(/\;/g, "");
        cleaned = cleaned.replace(/\^/g, "");
        cleaned = cleaned.replace(/\(/g, "");
        cleaned = cleaned.replace(/\)/g, "");
        cleaned = cleaned.replace(/\</g, "");
        cleaned = cleaned.replace(/\>/g, "");
        cleaned = cleaned.replace(/\[/g, "");
        cleaned = cleaned.replace(/\]/g, "");
        cleaned = cleaned.replace(/\,/g, "");
        return(cleaned);
    }

    function getQueryString(){
        var queryTargetString = '';
        if (window.location.search.length > 1)
        {
            queryTargetString = window.location.search.substring(1);
        }
        return cleanDFPParams(queryTargetString);
    }

    function getSubDomain(){
        var domainParts = window.location.hostname.split('.');
        return domainParts.shift();
    }

</script>
<script type='text/javascript'>
	const fusetag = window.fusetag || (window.fusetag = { que: [] });
	fusetag.que.push(function () {
		Object.keys(targetingAttributes).forEach(key => {
			fusetag.setTargeting(key, targetingAttributes[key]);
		});

		fusetag.registerZone("adDiv-topDesktop");
		fusetag.registerZone("adDiv-topMobile");
		fusetag.registerZone("adDiv1");
		fusetag.registerZone("contentDesktopAdDiv");
		fusetag.registerZone("contentPhoneAdDiv");
		fusetag.registerZone("sponsorLogoAdDiv");
		//fusetag.registerZone("adDiv-workout-raceCard-bottomDesktop-1");
		//fusetag.registerZone("adDiv-workout-raceCard-midDesktop-1");
		//fusetag.registerZone("adDiv-summary-entry-bottomDesktop-1");
		//fusetag.registerZone("adDiv-profile-bottomDesktop-1");
		//fusetag.registerZone("adDiv-horse-bottomDesktop-1");
		fusetag.registerZone("sidebar-video-desktop");
	});
</script>
<!-- end: defaultAdDef.cfm template -->

        <link rel="stylesheet" href="https://use.fontawesome.com/releases/v5.3.1/css/all.css" integrity="sha384-mzrmE5qonljUremFsqc01SB46JvROS7bZs3IO2EmfFsd15uHvIt+Y8vEf7N7fWAU" crossorigin="anonymous"/>
        <link rel="stylesheet" type="text/css" media="screen" href="/css/chardinjs.css">
        <link rel="stylesheet" type="text/css" media="screen" href="/css/site-components.css?version=20260611">
        <link rel="stylesheet" type="text/css" media="screen" href="/css/selectbox.css" />
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Roboto+Mono:ital,wght@0,100..700;1,100..700&display=swap" rel="stylesheet">
        <link href="https://fonts.googleapis.com/css?family=Raleway:900,800,600,400,200&display=swap" rel="stylesheet" type="text/css"  media="screen">
        <link rel="stylesheet" media="print" type="text/css" href="/css/printContentLayout.css?v=20260611" />
        <link rel="stylesheet" type="text/css" media="screen" href="/css/buttons.css" />
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">
        
            <script>
                var cookiePac = "";
                
            </script>
        

        <script src="/bundles/scripts-header.js?v=20260611"></script>
        <script src="/js/hoverIntent.js"></script>
        <script src="/js/superfish.js"></script>
        <script src="/js/chardinjs.min.js"></script>
        <script src="/js/main.js?v=20260611"></script>
        <script src="/js/jquery.selectbox-0.5.js"></script>
        <script src="/js/home/search.js?v=20260611"></script>
        <script src="/js/home/racing-news.js?v=20260611"></script>
        <script src="/js/recentPurchases.js?v=20260611"></script>
        <script src="https://content.jwplatform.com/libraries/Erc386SC.js"></script>
        <script>jwplayer.key="6h2q1dgYIzmCPurLH8UJZ8dJRSvyufS33mmXvA==";</script>

        <title>Equibase Racing Yearbook</title>
        <meta name="Description" content="Welcome to Equibase.com, your official source for horse racing results, mobile racing data, statistics as well as all other horse racing and thoroughbred racing information. Find everything you need to know about horse racing at Equibase.com." />
        <meta name="author" content="Equibase.com" />
        <meta name="Keywords" content="equibase, DRF, thoroughbred racing, mobile, statistics, race program, race, racing, racetracks, racetracks, race entries, race results, horse racing, expert selections, Daily Racing Form, TrackMaster, top leaders, jockeys, trainers, turf, owners, race results, horse, pedigrees, programs, sport of kings, databases, equine, horses, purebred, charts, crown, axcis, derby, breeders cup, bris, jockey club" />
        <meta name="norton-safeweb-site-verification" content="qgptd7c2-k6znysvtyi62yqtlg0s00z3yy3dsb6mrta5r51sx2zmzxy7-9bstj0a5wk558fk2e4dxme7wh9l4seye5ph8iqj-bsxtpuvkn19gsbvitez94ip4y0nvb1x" />

        <script>
            function keepSearch(sel) {
                $('[name=searchVal]').value = sel.value;
            }

            (function($){ //create closure so we can safely use $ as alias for jQuery
                $(document).ready(function(){
                    var exampleOptions = {
                         speed: 'fast'
                    }
                    // initialise plugin
                    var example = $('#example').superfish(exampleOptions);

                    // buttons to demonstrate Superfish's public methods
                    $('.destroy').on('click', function(){
                         example.superfish('destroy');
                    });

                    $('.init').on('click', function(){
                         example.superfish(exampleOptions);
                    });

                    $('.open').on('click', function(){
                         example.children('li:first').superfish('show');
                    });

                    $('.close').on('click', function(){
                         example.children('li:first').superfish('hide');
                    });

                    //Toggle Tabbed Content
                    $('.tab-info').hide();
                    $('#tab-one-info').show();
                    $('.tab-toggler').click(function (){
                        $('#tab-one-info').hide();
                        $('#' + $(this).attr('id') + '-info').addClass('active');
                        $('#' + $(this).attr('id') + '-info').show().siblings('.tab-info').hide();
                        $('#' + $(this).attr('id') + '-info').show().siblings('.tab-info').removeClass('active');
                        return false;
                    });

                    $(".tab-toggler").click(function() {
                        $(".tab-toggler").removeClass("active");
                        $(this).addClass("active");
                    });
                });
            })(jQuery);
        </script>

        
        

        <style>
            .show10People {height: 10px; overflow: hidden;}
            .showAllPeople {height: auto; width: 100%; margin: 0 auto;}
        </style>
    
    </head>
    <body>
        <!-- Google Tag Manager (noscript) -->
        <noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-TDBT73D"
                          height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>
        <!-- End Google Tag Manager (noscript) -->
        
        <section class="desktop-nav-wrapper">
            
                
                <div class="l-wrap-layout">
                    <div id="nav-bar" class="header-bar hidden-print phone-hide tablet-show desktop-show bg-green">
                        
                        <div class="customContainer">
                            <div class="row">
                                <div class="l-section-inner col-xs-12">
                                    
	<a href="/" class="equibase-logo">
		<img src="/img/equibase-logo.png" alt="Equibase">
	</a>
	<ul class="sf-menu header-tabs hidden-print ralewaymedium" id="primary-nav">
		<!-- pps-->
		<li class="current">
			<a href="/premium/eqbProductPage.cfm?pid=PP">PPs</a>
			<div class="sf-mega">
				<div class="">
					<h2 class="lightgreentxt text-uppercase">Thoroughbred</h2>
					<ol>
						<li><a href="/premium/eqbProductPage.cfm?pid=50300">Equibase Premium PP</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50201">Equibase Basic PP</a></li>
						<li><a href="/premium/eqpHorseLookup.cfm?PID=50214&SAP=TN">Lifetime PPs</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50316">TrackMaster Platinum PP</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50208">Daily Racing Form</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">Harness</h2>
					<ol>
						<li><a href="/premium/eqbProductPage.cfm?pid=50370">TrackMaster PPs</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50321">TrackMaster Platinum</a></li>
						<li><a href="/premium/eqpharnesspro.cfm?SAP=TNH">TrackMaster Harness Pro</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">More</h2>
					<ol>
						<li><a href="/products/handicapperstore.cfm?SAP=TN">Handicapper's Store</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=PP">View all PPs</a></li>
					</ol>
				</div>
			</div>
		</li>
		<!-- picks -->
		<li>
			<a href="/premium/eqbProductPage.cfm?pid=SEL" class="longtitle">Picks</a>
			<div class="sf-mega">
				<div class="">
					<h2 class="lightgreentxt text-uppercase">Picks</h2>
					<ol>
						<li><a href="/premium/eqbProductPage.cfm?pid=50630">Selections Bundle</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50289">F.A.S.T Sheets</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50267">Walker Group</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50292">Turf Club Analysts</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50237">Pace & Angles</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50233">Valuline </a></li>
						
						<li><a href="/premium/eqpAXCISHarnessSelections.cfm?SAP=TNH">Harness Selections</a></li>
						<li><a href="/static/eqpaxisselections.html">Shop by Track</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=SEL">Shop All Picks</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">Reports</h2>
					<ol>
						<li><a href="/premium/eqbProductPage.cfm?pid=50212">Flashnet</a></li>

						<li><a href="/premium/eqbProductPage.cfm?pid=50329">Thoro-Graph Full Sheets</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50328">Thoro-Graph Thoro-Quick</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50304">Thoro-Graph Form Ratings</a></li>
						<li><a href="/premium/eqbProductPage.cfm?pid=50495">Bruno With The Works </a></li>
					</ol>
				</div>
			</div>
		</li>
		<!-- race lens -->
		<li>
			<a href="#">Race Lens</a>
			<div class="sf-mega">
				<div class="no-h2">
					<ol>
						
						<li><a href="/premium/eqbProductPage.cfm?pid=50610&SAP=TN&REDIRECT_SUB=Y" >Race Lens</a></li>
						
						<li><a href="/premium/eqbProductPage.cfm?pid=50620&Incltxt=eqpViewStatstrueoddsSub.cfm&REDIRECT_SUB=Y">True Odds</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">More Information</h2>
					<ol>
						<li><a href="/Data.cfm/Product/STATS/FreeRace?productCode=SRL" onClick="gtag('send', 'event', 'Nav Bar', 'click' 'STATS Race Lens Free Race');" target="_blank">Free Race</a></li>
						<li><a href="/products/whatisracelens.cfm">Product Education</a></li>
						<li><a href="/products/racelens-comparison.cfm">Compare Plans</a></li>
						<li><a href="/content/podcast/Handicapping.cfm">Podcasts/Webinars</a></li>
						<li><a href="/content/NHC/racetothenhc.cfm">Race to the NHC Contests</a></li>
					</ol>
				</div>
			</div>
		</li>
		<!-- entries -->
		<li>
			<a href="/static/entry/index.html?SAP=TN">Entries</a>
			<div class="sf-mega">
				<div class="">
					<h2 class="lightgreentxt text-uppercase">All Entries</h2>
					<ol>
						<li><a href="/static/entry/index.html?SAP=TN">Thoroughbred</a></li>
						<li><a href="/static/foreign/entry/index.html?SAP=TN">International</a></li>
						<li><a href="/premium/eqbstakesentries.cfm?SAP=TN">Stakes</a></li>
						<li><a href="/static/harness/entry/index.html?SAP=TNH">Harness</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">More Information</h2>
					<ol>
						<li><a href="/static/latechanges/html/latechanges.html?SAP=TN">Race Day Changes</a></li>
						<li><a href="/static/latechanges/html/cancellations.html?SAP=TN">Cancellations</a></li>
						<li><a href="/static/workout/index.html?SAP=TN">Workouts</a></li>
						<li><a href="/premium/eqpCarryoverCorner.cfm?SAP=TN">Carryovers</a></li>
						<li><a href="/premium/pubentriesplus.cfm">Entries Plus</a></li>
						<li><a href="/products/racedates.cfm?SAP=TN">Race Dates & Calendar</a></li>
						<li><a href="/premium/eqpInToday.cfm?SAP=TN">In Today</a></li>
					</ol>
				</div>
			</div>
		</li>
		<!-- results -->
		<li>
			<a href="/static/chart/pdf/index.html?SAP=TN">Results </a>
			<div class="sf-mega">
				<div class="no-h2">
					<ol>
						<li><a href="/static/chart/pdf/index.html?SAP=TN">Full Charts </a></li>
						<li><a href="/static/chart/summary/index.html?SAP=TN">Summary Results</a></li>
						<li><a href="/static/foreign/result/index.html?SAP=TN">International</a></li>
						<li><a href="/premium/eqbRaceChartCalendar.cfm?SAP=TN">Historical Charts </a></li>
						<li><a href="/premium/eqpVideoRaceReplaysSearch.cfm?SAP=TN">Race Replays</a></li>
						<li><a href="/premium/eqpTMResultChartSearch.cfm?SAP=TN">Downloadable Charts</a></li>
						<li><a href="/results/stakesresults.cfm">Stakes</a></li>
						<li><a href="/glossary.cfm">Glossary</a></li>
					</ol>
				</div>
			</div>
		</li>
		<!-- leaders -->
		<li>
			<a href="/stats/View.cfm?tf=year&tb=horse">Leaders</a>
			<div class="sf-mega">
				<div class="">
					<h2 class="lightgreentxt text-uppercase">Thoroughbred</h2>
					<ol>
						<li><a href="/stats/View.cfm?tf=year&rbt=TB">Leaders By Year</a></li>
						<li><a href="/stats/View.cfm?tf=meet&rbt=TB">Leaders by Track</a></li>
						<li><a href="/stats/ViewAllTime.cfm?tf=all-time&rbt=TB">All-Time Leaders</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">Quarter Horse</h2>
					<ol>
						<li><a href="/stats/View.cfm?tf=year&rbt=QH">Leaders By Year</a></li>
						<li><a href="/stats/View.cfm?tf=meet&rbt=QH">Leaders by Track</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">More Information</h2>
					<ol>
						<li><a href="/static/statistics/eleaders.html">E-Speed Figures</a></li>
						<li><a href="/about/northamericanrecords.cfm">North American Records</a></li>
						<li><a href="/content/ifharatings-home.cfm">IFHA World Rankings</a></li>
						<li><a href="/compare/index.cfm">Compare Statistics</a></li>
						<li><a href="/dailyInsights/dailyInsights.cfm">Daily Insights</a></li>
						<li><a href="/premium/eqpJTStandings.cfm">Meet Stats</a></li>
					</ol>
				</div>
			</div>
		</li>
		<!-- horsemen -->
		<li>
			<a href="/static/horsemen/horsemenarea.html?SAP=TN" >Horsemen</a>
			<div class="sf-mega">
				<div class="no-h2">
					<ol>
						<li><a href="/static/horsemen/horsemenareaCB.html?SAP=TN">Condition Books</a></li>
						<li><a href="/static/horsemen/horsemenareaON.html?SAP=TN">Overnights</a></li>
						<li><a href="/static/horsemen/horsemenareaSB.html?SAP=TN">Stakes Book</a></li>
						<li><a href="/static/horsemen/horsemenareaSNHW.html?SAP=TN">Stakes Nominations</a></li>
						<li><a href="/ratings/index.cfm">Horse Rating FAQ</a></li>
					</ol>
				</div>
			</div>
		</li>
		<!-- virtural stables -->
		<li>
			<a href="/virtualstable/horse.cfm">Virtual Stable</a>
			<div class="sf-mega">
				<div class="no-h2">
					<ol>
						<li><a href="/virtualstable/horse.cfm">Horses</a></li>
						<li><a href="/virtualstable/jockey.cfm">Jockeys</a></li>
						<li><a href="/virtualstable/trainer.cfm">Trainers</a></li>
						<li><a href="/virtualstable/track.cfm">Tracks</a></li>
						<li><a href="/virtualstable/raceseries.cfm">Race Series</a></li>
						<li><a href="/virtualstable/stakes.cfm">Stakes</a></li>
						<li><a href="/virtualstable/carryover.cfm">Carryovers</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">More Information</h2>
					<ol>
						<li><a href="/about/virtualstableinfo.cfm">About Virtual Stable</a></li>
						<li><a href="/virtualstable/horseNotification.cfm?SID=1">View My Notifications</a></li>
					</ol>
				</div>
			</div>
		</li>
		<!-- more -->
		<li>
			<a href="#">More</a>
			<div class="sf-mega">
				<div class="no-h2">
					<ol>	<li><a href="https://www.equibase.com/content/forms/feedback.cfm">Customer Feedback</a></li>
						<li><a href="/about/equibaseapp.cfm"><img src="/img/icons/app.svg"/>Equibase App</a></li>
						<li><a href="/premium/eqbCustomerOffers.cfm"><img src="/img/icons/gift_offer.svg"/>My Offers</a></li>
						<li><a href="/content/podcast/Handicapping.cfm">Podcasts/Webinars</a></li>
					</ol>

					<h2 class="lightgreentxt text-uppercase">Free Information</h2>
					<ol>
						<li><a href="/rotd/index.cfm?SAP=TN">Race of the Day</a></li>
						<li><a href="/free/index.cfm?SAP=TN">Race of the Week</a></li>
						<li><a href="/products/freepicks2.cfm?SAP=TN">Picks</a></li>
						<li><a href="/content/wageringtools/index.cfm">Wagering Tools</a></li>
						<li><a href="/yearbook/">Racing Yearbook</a></li>
						<li><a href="/news/newsAggregation.cfm">Latest News</a></li>
						<li><a href="/about/adw.cfm">Wagering Services</a></li>
						<li><a href="/handicappersdata.cfm">Free Dataset</a></li>
						<li><a href="/marketplace/index2.cfm">Marketplace</a></li>
					</ol>
				</div>
			</div>
		</li>
	</ul>

                                    <ul class="social-icons account-social-icon">
                                        <li class="menu-search-display">
                                            <div class="search hidden-print">
                                                
    <div class="searchbar">
        <form name="search" class="header-search-form" method="post">
            <div>
                <select name="searchOptions" onchange="javascript:keepSearch(this);">
                    <option value="horses" data-placeholder="Horse Name">Horses</option>
                    <option value="jockeys" data-placeholder="Last Name">Jockeys</option>
                    <option value="trainers" data-placeholder="Last Name">Trainers</option>
                    <option value="owners" data-placeholder="Last/Stable/Syndicate Name">Owners</option>
                    <option value="tracks" data-placeholder="Track Name">Tracks</option>
                    <option value="stakes" data-placeholder="Graded Stakes Name">Gr. Stakes</option>
                </select>
                <input type="hidden" value="horses" name="searchVal">
                <input class="input" name="searchInput" type="text" placeholder=""/>
                <input type="submit"value="">
            </div>
        </form>
    </div>
    <script>
        $(document).ready(function(){
            
                $('[name=searchOptions]').val("horses");
            
            $('[name=searchOptions]').trigger("change");
        });
    </script>

                                            </div>
                                        </li>
                                    </ul>
                                    <ul class="sf-menu hidden-print ralewaymedium account-checkout-header" id="secondary-nav">
                                        <li><a href="/about/faq.cfm "><img src="/img/icons/info.svg"></a></li>
                                        <li>
                                            <a href="/premium/customeradminmain.cfm?logon=Y"><img src="/img/icons/account.svg"></a>
                                            <div class="sf-mega">
    <div class="account-logged-in">
        <ol>
            <li><a href="/premium/customeradminmain.cfm">Account Services</a></li>
            <li><a href="/virtualstable/login.cfm?SID=1">Virtual Stable</a></li>
            <li><a href="/premium/eebCustomerAccountHistorySelect.cfm">Order History</a></li>
            <li><a href="/premium/eqbCustomerOffers.cfm">Offers and Promotions</a></li>
            <li><a href="/premium/eebDownloadProduct.cfm">View All Recent Purchases</a></li>
            <li><a href="/premium/eebCustomerLogout.cfm">Log out</a>
        </ol>
    </div>
    <div class="account-login">
        <ol>
            <li><a href="/premium/customeradminmain.cfm?logon=Y">Login</a></li>
        </ol>
    </div>
</div>
                                        </li>
                                        <li><a href="/premium/eebCustomerCheckoutLogon.cfm"><img src="/img/icons/cart.svg"></a></li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            
        </section>
        <section id="ad-bar">
        	
        </section>
        <section id="site-bar">
            <div class="l-section-inner row desktop-hide tablet-hide">
                <div class="col-xs-1">
                    <a id="mobile-nav-bar-toggle" class="btn-mobile-menu-toggle"><img src="/img/mob-nav-icon.png" alt="Equibase" class="menu-logo"></a>
                </div>
                <div class="col-xs-1">
                    <a href="/premium/customeradminmain.cfm?logon=Y"><img src="/img/icons/account.svg" alt="Account" class="menu-logo"></a>
                </div>
                <div class="col-xs-8 center">
                    <a href="/"><img src="/img/equibase-logo.png" alt="Equibase" class="equibase-phone-logo"></a>
                </div>
                <div class="col-xs-1" id="mobile-search-icon">
                    <img src="/img/icons/search_white.svg" alt="Search" class="menu-logo">
                </div>
                <div class="col-xs-1">
                    <a href="/premium/eebCustomerCheckoutLogon.cfm"><img src="/img/icons/cart.svg" alt="Cart" class="menu-logo"></a>
                </div>
                <nav class="desktop-hide tablet-hide">
                    
	<ul class="menu-bar ralewaymedium">
		<!-- pps-->
		<li class="menu-toggle">
			<a>PPs</a>
			<ul class="menu-bar sub-menu">
				<h2 class="lightgreentxt text-uppercase">Thoroughbred</h2>
				<ol>
					<li><a href="/premium/eqbProductPage.cfm?pid=50300">Equibase Premium PP</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50201">Equibase Basic PP</a></li>
					<li><a href="/premium/eqpHorseLookup.cfm?PID=50214&SAP=TN">Lifetime PPs</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50316">TrackMaster Platinum PP</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50208">Daily Racing Form</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">Harness</h2>
				<ol>
					<li><a href="/premium/eqbProductPage.cfm?pid=50370">TrackMaster PPs</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50321">TrackMaster Platinum</a></li>
					<li><a href="/premium/eqpharnesspro.cfm?SAP=TNH">TrackMaster Harness Pro</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">More</h2>
				<ol>
					<li><a href="/products/handicapperstore.cfm?SAP=TN">Handicapper's Store</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=PP">View all PPs</a></li>
				</ol>
			</ul>
		</li>
		<!-- picks -->
		<li class="menu-toggle">
			<a>Picks</a>
			<ul class="menu-bar sub-menu">
				<h2 class="lightgreentxt text-uppercase">Picks</h2>
				<ol>
					<li><a href="/premium/eqbProductPage.cfm?pid=50630">Selections Bundle</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50289">F.A.S.T Sheets</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50267">Walker Group</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50292">Turf Club Analysts</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50237">Pace & Angles</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50233">Valuline </a></li>
					
					<li><a href="/premium/eqpAXCISHarnessSelections.cfm?SAP=TNH">Harness Selections</a></li>
					<li><a href="/static/eqpaxisselections.html">Shop by Track</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=SEL">Shop All Picks</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">Reports</h2>
				<ol>
					<li><a href="/premium/eqbProductPage.cfm?pid=50212">Flashnet</a></li>

					<li><a href="/premium/eqbProductPage.cfm?pid=50329">Thoro-Graph Full Sheets</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50328">Thoro-Graph Thoro-Quick</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50304">Thoro-Graph Form Ratings</a></li>
					<li><a href="/premium/eqbProductPage.cfm?pid=50495">Bruno With The Works </a></li>
				</ol>
			</ul>
		</li>
		
		<li class="menu-toggle">
			<a>Race Lens</a>
			<ul class="menu-bar sub-menu">
				<ol>
					
					<li><a href="/premium/eqbProductPage.cfm?pid=50610&SAP=TN&REDIRECT_SUB=Y" >Race Lens</a></li>
					
					<li><a href="/premium/eqbProductPage.cfm?pid=50620&Incltxt=eqpViewStatstrueoddsSub.cfm&REDIRECT_SUB=Y">True Odds</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">More Information</h2>
				<ol>
					<li><a href="/Data.cfm/Product/STATS/FreeRace?productCode=SRL" onClick="gtag('send', 'event', 'Nav Bar', 'click' 'STATS Race Lens Free Race');" target="_blank">Free Race</a></li>
					<li><a href="/products/whatisracelens.cfm">Product Education</a></li>
					<li><a href="/products/racelens-comparison.cfm">Compare Plans</a></li>
					<li><a href="/content/podcast/Handicapping.cfm">Podcasts/Webinars</a></li>
					<li><a href="/content/NHC/racetothenhc.cfm">Race to the NHC Contests</a></li>
				</ol>
			</ul>
		</li>
		<!-- entries -->
		<li class="menu-toggle">
			<a>Entries</a>
			<ul class="menu-bar sub-menu">
				<h2 class="lightgreentxt text-uppercase">All Entries</h2>
				<ol>
					<li><a href="/static/entry/index.html?SAP=TN">Thoroughbred</a></li>
					<li><a href="/static/foreign/entry/index.html?SAP=TN">International</a></li>
					<li><a href="/premium/eqbstakesentries.cfm?SAP=TN">Stakes</a></li>
					<li><a href="/static/harness/entry/index.html?SAP=TNH">Harness</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">More Information</h2>
				<ol>
					<li><a href="/static/latechanges/html/latechanges.html?SAP=TN">Race Day Changes</a></li>
					<li><a href="/static/latechanges/html/cancellations.html?SAP=TN">Cancellations</a></li>
					<li><a href="/static/workout/index.html?SAP=TN">Workouts</a></li>
					<li><a href="/premium/eqpCarryoverCorner.cfm?SAP=TN">Carryovers</a></li>
					<li><a href="/premium/pubentriesplus.cfm">Entries Plus</a></li>
					<li><a href="/products/racedates.cfm?SAP=TN">Race Dates & Calendar</a></li>
					<li><a href="/premium/eqpInToday.cfm?SAP=TN">In Today</a></li>
				</ol>
			</ul>
		</li>
		<!-- results -->
		<li class="menu-toggle">
			<a>Results </a>
			<ul class="menu-bar sub-menu">
				<ol>
					<li><a href="/static/chart/pdf/index.html?SAP=TN">Full Charts </a></li>
					<li><a href="/static/chart/summary/index.html?SAP=TN">Summary Results</a></li>
					<li><a href="/static/foreign/result/index.html?SAP=TN">International</a></li>
					<li><a href="/premium/eqbRaceChartCalendar.cfm?SAP=TN">Historical Charts </a></li>
					<li><a href="/premium/eqpVideoRaceReplaysSearch.cfm?SAP=TN">Race Replays</a></li>
					<li><a href="/premium/eqpTMResultChartSearch.cfm?SAP=TN">Downloadable Charts</a></li>
					<li><a href="/results/stakesresults.cfm">Stakes</a></li>
					<li><a href="/glossary.cfm">Glossary</a></li>
				</ol>
			</ul>
		</li>
		<!-- Leaders -->
		<li class="menu-toggle">
			<a>Leaders</a>
			<ul class="menu-bar sub-menu">
				<h2 class="lightgreentxt text-uppercase">Thoroughbred</h2>
				<ol>
					<li><a href="/stats/View.cfm?tf=year&rbt=TB">Leaders By Year</a></li>
					<li><a href="/stats/View.cfm?tf=meet&rbt=TB">Leaders by Track</a></li>
					<li><a href="/stats/ViewAllTime.cfm?tf=all-time&rbt=TB">All-Time Leaders</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">Quarter Horse</h2>
				<ol>
					<li><a href="/stats/View.cfm?tf=year&rbt=QH">Leaders By Year</a></li>
					<li><a href="/stats/View.cfm?tf=meet&rbt=QH">Leaders by Track</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">More Information</h2>
				<ol>
					<li><a href="/static/statistics/eleaders.html">E-Speed Figures</a></li>
					<li><a href="/about/northamericanrecords.cfm">North American Records</a></li>
					<li><a href="/content/ifharatings-home.cfm">IFHA World Rankings</a></li>
					<li><a href="/compare/index.cfm">Compare Statistics</a></li>
					<li><a href="/dailyInsights/dailyInsights.cfm">Daily Insights</a></li>
					<li><a href="/premium/eqpJTStandings.cfm">Meet Stats</a></li>
				</ol>
			</ul>
		</li>
		<!-- horsemen -->
		<li class="menu-toggle">
			<a>Horsemen</a>
			<ul class="menu-bar sub-menu">
				<ol>
					<li><a href="/static/horsemen/horsemenareaCB.html?SAP=TN">Condition Books</a></li>
					<li><a href="/static/horsemen/horsemenareaON.html?SAP=TN">Overnights</a></li>
					<li><a href="/static/horsemen/horsemenareaSB.html?SAP=TN">Stakes Book</a></li>
					<li><a href="/static/horsemen/horsemenareaSNHW.html?SAP=TN">Stakes Nominations</a></li>
					<li><a href="/ratings/index.cfm">Horse Rating FAQ</a></li>
				</ol>
			</ul>
		</li>
		<!-- virtural stables -->
		<li class="menu-toggle">
			<a>Virtual Stable</a>
			<ul class="menu-bar sub-menu">
				<ol>
					<li><a href="/virtualstable/horse.cfm">Horses</a></li>
					<li><a href="/virtualstable/jockey.cfm">Jockeys</a></li>
					<li><a href="/virtualstable/trainer.cfm">Trainers</a></li>
					<li><a href="/virtualstable/track.cfm">Tracks</a></li>
					<li><a href="/virtualstable/raceseries.cfm">Race Series</a></li>
					<li><a href="/virtualstable/stakes.cfm">Stakes</a></li>
					<li><a href="/virtualstable/carryover.cfm">Carryovers</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">More Information</h2>
				<ol>
					<li><a href="/about/virtualstableinfo.cfm">About Virtual Stable</a></li>
					<li><a href="/virtualstable/horseNotification.cfm?SID=1">View My Notifications</a></li>
				</ol>
			</ul>
		</li>
		<!-- more -->
		<li class="menu-toggle">
			<a>More</a>
			<ul class="menu-bar sub-menu">
				<ol>
			<li><a href="https://www.equibase.com/content/forms/feedback.cfm">Customer Feedback</a></li>
					<li><a href="/about/equibaseapp.cfm"><img src="/img/icons/app.svg"/>Equibase App</a></li>
					<li><a href="/premium/eqbCustomerOffers.cfm"><img src="/img/icons/gift_offer.svg"/>My Offers</a></li>
					<li><a href="/content/podcast/Handicapping.cfm">Podcasts/Webinars</a></li>
				</ol>

				<h2 class="lightgreentxt text-uppercase">Free Information</h2>
				<ol>

					<li><a href="/rotd/index.cfm?SAP=TN">Race of the Day</a></li>
					<li><a href="/free/index.cfm?SAP=TN">Race of the Week</a></li>
					<li><a href="/products/freepicks2.cfm?SAP=TN">Picks</a></li>
					<li><a href="/content/wageringtools/index.cfm">Wagering Tools</a></li>
					<li><a href="/yearbook/">Racing Yearbook</a></li>
					<li><a href="/news/newsAggregation.cfm">Latest News</a></li>
					<li><a href="/about/adw.cfm">Wagering Services</a></li>
					<li><a href="/handicappersdata.cfm">Free Dataset</a></li>
					<li><a href="/marketplace/index2.cfm">Marketplace</a></li>
				</ol>
			</ul>
		</li>
		<!-- help -->
		<li class="menu-toggle">
			<a>Help</a>
			<ul class="menu-bar sub-menu">
				<ol>
					<li><a href="/about/faq.cfm ">FAQs</a></li>
					<li><a href="/about/about.cfm">About Us</a></li>
					<li><a href="/about/contact.cfm">Contact Us</a></li>
				</ol>
			</ul>
		</li>
	</ul>

                </nav>
            </div>
            <div id="mobile-search" class="l-section-inner row desktop-hide hidden">
                <div class="col-xs-12">
                    
    <div class="searchbar">
        <form name="search" class="header-search-form" method="post">
            <div>
                <select name="searchOptions" onchange="javascript:keepSearch(this);">
                    <option value="horses" data-placeholder="Horse Name">Horses</option>
                    <option value="jockeys" data-placeholder="Last Name">Jockeys</option>
                    <option value="trainers" data-placeholder="Last Name">Trainers</option>
                    <option value="owners" data-placeholder="Last/Stable/Syndicate Name">Owners</option>
                    <option value="tracks" data-placeholder="Track Name">Tracks</option>
                    <option value="stakes" data-placeholder="Graded Stakes Name">Gr. Stakes</option>
                </select>
                <input type="hidden" value="horses" name="searchVal">
                <input class="input" name="searchInput" type="text" placeholder=""/>
                <input type="submit"value="">
            </div>
        </form>
    </div>
    <script>
        $(document).ready(function(){
            
                $('[name=searchOptions]').val("horses");
            
            $('[name=searchOptions]').trigger("change");
        });
    </script>

                </div>
            </div>

            
            <!-- Ad Display / Header Banner -->
<!-- BEGIN AD -->


<div id="headerAdWrapperDiv" class="header-ad hidden-print">
    <div id="adDiv-topDesktop" data-fuse="desktop" class="hidden-print phone-hide ad-top-banner" style="z-index: 100;"></div>
    
    <div id="adDiv-topMobile" data-fuse="mobile" class="hidden-print tablet-hide desktop-hide ad-top-banner" style="z-index: 3;"></div>
</div>
<!-- END AD -->
        </section>
        <style type="text/css">
            .blockbg {
                background: #fff;
                border: 1px solid #bab7ae;
                border-top: 10px solid #bab7ae;
                padding: 15px;
            }
            .component.spaced {
                margin-bottom: 20px;
            }
        </style>
        <section id="page-bar" class="l-section desktop-content-wrapper">

    <style type="text/css" media="all">@import "/css/south-street/jquery-ui-1.8.10.custom.css";</style>
    <script src="/js/plugins/jquery.swfobject.1-1-1.min.js" type="text/javascript" charset="utf-8"></script>
    <script src="/js/webYearbook.js" type="text/javascript" charset="utf-8"></script>
    <script src="../js/home/abrRaces.js" type="text/javascript" charset="utf-8"></script>

    <script type="text/javascript">
        $(function(){
            var race = new Object();
race["racedescription2"] = " By subscription of $100 each or by supplementary nomination of $3,000 at time of entry. $500 to pass the entry box; $500 additional to start, with $100,000 guaranteed. After payment of 1% to all owners of horses finishing sixth through last, 62% of the remaining purse shall be paid to the owner of the winner, 20% to second, 10% to third, 5% to fourth and 3% to fifth.  Weights: Three year olds, 122 Lbs. Older, 125 Lbs.  Non-winners of a Grade I stakes in 2018, allowed 2 Lbs.; a Grade II or Grade III stakes at a mile or over in 2018, 4 Lbs. The maximum numbers of starters for the Ack Ack will be limited to fourteen (14).  If more than fourteen (14) entries pass the entry box preference will be given to graded stakes winners (in order I-II-III), then highest 2018 earnings.  Any horse excluded from running because of the aforementioned preference shall be refunded the entry fee and supplementary nomination fee if applicable. Starters to be named through the entry box by the usual time of closing. All supplementary nominations will be required to pay entry and starting fees if they participate. A trophy will be presented to the winning owner. Closed Saturday, September 15, 2018 with 23 nominations.";
race["stakesindicator"] = "Y";
race["racedescription1"] = "For Three-Year-Olds And Upward.";
race["tracklink"] = "/profiles/Results.cfm?type=Track&trk=CD&cy=USA";
race["dayevening"] = "D";
race["stakeid"] = 2413;
race["trackcondition"] = "Fast";
race["winningtime"] = 13501;
race["nextnumber"] = 9;
race["claim"] = "";
race["scratches"] =  new Array();
race["scratches"][0] = new Object();
race["scratches"][0]["odds"] = 0;
race["scratches"][0]["breedername"] = "";
race["scratches"][0]["sirehorsename"] = "Flatter";
race["scratches"][0]["disqualified"] = false;
race["scratches"][0]["scratchreason"] = "Trainer";
race["scratches"][0]["programnumber"] = "SCR";
race["scratches"][0]["horse"] = new Object();
race["scratches"][0]["horse"]["referencenumber"] = 9286291;
race["scratches"][0]["horse"]["sex"] = "Gelding";
race["scratches"][0]["horse"]["foalingdate"] =  new Date(2012, 1, 5, 0, 0, 0);
race["scratches"][0]["horse"]["breedtype"] = "TB";
race["scratches"][0]["horse"]["name"] = "Flatlined";
race["scratches"][0]["horse"]["registry"] = "T";
race["scratches"][0]["placepayoff"] = 0.0000;
race["scratches"][0]["scratchindicator"] = true;
race["scratches"][0]["showpayoff"] = 0.0000;
race["scratches"][0]["owner"] = new Object();
race["scratches"][0]["owner"]["identity"] = 1999829;
race["scratches"][0]["owner"]["middlename"] = "";
race["scratches"][0]["owner"]["lastname"] = "Hytrek, Brian, Paden, Rodney and Kuhn, Ryan";
race["scratches"][0]["owner"]["firstname"] = "";
race["scratches"][0]["owner"]["type"] = "O6";
race["scratches"][0]["postposition"] = 99;
race["scratches"][0]["trainer"] = new Object();
race["scratches"][0]["trainer"]["identity"] = 5440;
race["scratches"][0]["trainer"]["middlename"] = "L.";
race["scratches"][0]["trainer"]["lastname"] = "Dickey";
race["scratches"][0]["trainer"]["firstname"] = "Charles";
race["scratches"][0]["trainer"]["type"] = "TE";
race["scratches"][0]["officialposition"] = 0;
race["scratches"][0]["mutuelposition"] = 0;
race["scratches"][0]["finishposition"] = 0;
race["scratches"][0]["deadheat"] = false;
race["scratches"][0]["sireofdamhorsename"] = "Unbridled\'s Song";
race["scratches"][0]["winpayoff"] = 0.0000;
race["scratches"][0]["jockey"] = new Object();
race["scratches"][0]["jockey"]["identity"] = 70746;
race["scratches"][0]["jockey"]["middlename"] = "";
race["scratches"][0]["jockey"]["lastname"] = "Rocco, Jr.";
race["scratches"][0]["jockey"]["firstname"] = "Joseph";
race["scratches"][0]["jockey"]["type"] = "JE";
race["scratches"][0]["damhorsename"] = "Buttercup\'s Song";
race["bcchallengeindicator"] = "";
race["temporaryraildistance"] = "";
race["exoticpayoffs"] =  new Array();
race["exoticpayoffs"][0] = new Object();
race["exoticpayoffs"][0]["payoffamount"] = 85.3000;
race["exoticpayoffs"][0]["numberofrights"] = 3;
race["exoticpayoffs"][0]["wageramount"] = 0.5;
race["exoticpayoffs"][0]["type"] = "3";
race["exoticpayoffs"][0]["winningnumbers"] = "7-5-6";
race["exoticpayoffs"][0]["name"] = "Pick 3";
race["exoticpayoffs"][1] = new Object();
race["exoticpayoffs"][1]["payoffamount"] = 18.3000;
race["exoticpayoffs"][1]["numberofrights"] = 0;
race["exoticpayoffs"][1]["wageramount"] = 1.0;
race["exoticpayoffs"][1]["type"] = "D";
race["exoticpayoffs"][1]["winningnumbers"] = "5-6";
race["exoticpayoffs"][1]["name"] = "Daily Double";
race["exoticpayoffs"][2] = new Object();
race["exoticpayoffs"][2]["payoffamount"] = 179.0000;
race["exoticpayoffs"][2]["numberofrights"] = 0;
race["exoticpayoffs"][2]["wageramount"] = 2.0;
race["exoticpayoffs"][2]["type"] = "E";
race["exoticpayoffs"][2]["winningnumbers"] = "6-5";
race["exoticpayoffs"][2]["name"] = "Exacta";
race["exoticpayoffs"][3] = new Object();
race["exoticpayoffs"][3]["payoffamount"] = 58.5100;
race["exoticpayoffs"][3]["numberofrights"] = 0;
race["exoticpayoffs"][3]["wageramount"] = 0.1;
race["exoticpayoffs"][3]["type"] = "S";
race["exoticpayoffs"][3]["winningnumbers"] = "6-5-2-7";
race["exoticpayoffs"][3]["name"] = "Superfecta";
race["exoticpayoffs"][4] = new Object();
race["exoticpayoffs"][4]["payoffamount"] = 146.1500;
race["exoticpayoffs"][4]["numberofrights"] = 0;
race["exoticpayoffs"][4]["wageramount"] = 0.5;
race["exoticpayoffs"][4]["type"] = "T";
race["exoticpayoffs"][4]["winningnumbers"] = "6-5-2";
race["exoticpayoffs"][4]["name"] = "Trifecta";
race["surface"] = "";
race["derbyseriesindicator"] = "";
race["breed"] = "TB";
race["type"] = "STAKES";
race["surfacedescription"] = "Dirt";
race["previousnumber"] = 7;
race["officialindicator"] = "Y";
race["number"] = 8;
race["distance"] = "One Mile";
race["gradeexpanded"] = "(Grade III)";
race["minclaim"] = 0.0000;
race["starters"] =  new Array();
race["starters"][0] = new Object();
race["starters"][0]["odds"] = 360;
race["starters"][0]["breedername"] = "Charles Fipke";
race["starters"][0]["sirehorsename"] = "Perfect Soul (IRE)";
race["starters"][0]["disqualified"] = false;
race["starters"][0]["scratchreason"] = "";
race["starters"][0]["programnumber"] = "6";
race["starters"][0]["horse"] = new Object();
race["starters"][0]["horse"]["referencenumber"] = 9512495;
race["starters"][0]["horse"]["sex"] = "Horse";
race["starters"][0]["horse"]["keenelandgrad"] = true;
race["starters"][0]["horse"]["foalingdate"] =  new Date(2013, 4, 4, 0, 0, 0);
race["starters"][0]["horse"]["breedtype"] = "TB";
race["starters"][0]["horse"]["name"] = "Seeking the Soul";
race["starters"][0]["horse"]["registry"] = "T";
race["starters"][0]["placepayoff"] = 5.2000;
race["starters"][0]["scratchindicator"] = false;
race["starters"][0]["showpayoff"] = 3.4000;
race["starters"][0]["owner"] = new Object();
race["starters"][0]["owner"]["identity"] = 786617;
race["starters"][0]["owner"]["middlename"] = "E.";
race["starters"][0]["owner"]["lastname"] = "Fipke";
race["starters"][0]["owner"]["firstname"] = "Charles";
race["starters"][0]["owner"]["type"] = "O6";
race["starters"][0]["postposition"] = 5;
race["starters"][0]["trainer"] = new Object();
race["starters"][0]["trainer"]["identity"] = 135878;
race["starters"][0]["trainer"]["middlename"] = "";
race["starters"][0]["trainer"]["lastname"] = "Stewart";
race["starters"][0]["trainer"]["firstname"] = "Dallas";
race["starters"][0]["trainer"]["type"] = "TE";
race["starters"][0]["officialposition"] = 1;
race["starters"][0]["mutuelposition"] = 1;
race["starters"][0]["finishposition"] = 1;
race["starters"][0]["deadheat"] = false;
race["starters"][0]["sireofdamhorsename"] = "Seeking the Gold";
race["starters"][0]["winpayoff"] = 9.2000;
race["starters"][0]["jockey"] = new Object();
race["starters"][0]["jockey"]["identity"] = 109036;
race["starters"][0]["jockey"]["middlename"] = "Joseph";
race["starters"][0]["jockey"]["lastname"] = "Hernandez, Jr.";
race["starters"][0]["jockey"]["firstname"] = "Brian";
race["starters"][0]["jockey"]["type"] = "JE";
race["starters"][0]["damhorsename"] = "Seeking the Title";
race["starters"][1] = new Object();
race["starters"][1]["odds"] = 2240;
race["starters"][1]["breedername"] = "";
race["starters"][1]["sirehorsename"] = "Twirling Candy";
race["starters"][1]["disqualified"] = false;
race["starters"][1]["scratchreason"] = "";
race["starters"][1]["programnumber"] = "5";
race["starters"][1]["horse"] = new Object();
race["starters"][1]["horse"]["referencenumber"] = 9755573;
race["starters"][1]["horse"]["sex"] = "Gelding";
race["starters"][1]["horse"]["keenelandgrad"] = false;
race["starters"][1]["horse"]["foalingdate"] =  new Date(2014, 2, 23, 0, 0, 0);
race["starters"][1]["horse"]["breedtype"] = "TB";
race["starters"][1]["horse"]["name"] = "Nice Not Nice";
race["starters"][1]["horse"]["registry"] = "T";
race["starters"][1]["placepayoff"] = 12.6000;
race["starters"][1]["scratchindicator"] = false;
race["starters"][1]["showpayoff"] = 4.8000;
race["starters"][1]["owner"] = new Object();
race["starters"][1]["owner"]["identity"] = 1494603;
race["starters"][1]["owner"]["middlename"] = "";
race["starters"][1]["owner"]["lastname"] = "Keene Ridge Racing LLC";
race["starters"][1]["owner"]["firstname"] = "";
race["starters"][1]["owner"]["type"] = "O6";
race["starters"][1]["postposition"] = 4;
race["starters"][1]["trainer"] = new Object();
race["starters"][1]["trainer"]["identity"] = 37430;
race["starters"][1]["trainer"]["middlename"] = "B.";
race["starters"][1]["trainer"]["lastname"] = "Bradley";
race["starters"][1]["trainer"]["firstname"] = "William";
race["starters"][1]["trainer"]["type"] = "TE";
race["starters"][1]["officialposition"] = 2;
race["starters"][1]["mutuelposition"] = 2;
race["starters"][1]["finishposition"] = 2;
race["starters"][1]["deadheat"] = false;
race["starters"][1]["sireofdamhorsename"] = "Broken Vow";
race["starters"][1]["winpayoff"] = 0.0000;
race["starters"][1]["jockey"] = new Object();
race["starters"][1]["jockey"]["identity"] = 121307;
race["starters"][1]["jockey"]["middlename"] = "";
race["starters"][1]["jockey"]["lastname"] = "Saez";
race["starters"][1]["jockey"]["firstname"] = "Gabriel";
race["starters"][1]["jockey"]["type"] = "JE";
race["starters"][1]["damhorsename"] = "Kiss Is a Kiss";
race["starters"][2] = new Object();
race["starters"][2]["odds"] = 380;
race["starters"][2]["breedername"] = "";
race["starters"][2]["sirehorsename"] = "Frost Giant";
race["starters"][2]["disqualified"] = false;
race["starters"][2]["scratchreason"] = "";
race["starters"][2]["programnumber"] = "2";
race["starters"][2]["horse"] = new Object();
race["starters"][2]["horse"]["referencenumber"] = 9526657;
race["starters"][2]["horse"]["sex"] = "Horse";
race["starters"][2]["horse"]["keenelandgrad"] = true;
race["starters"][2]["horse"]["foalingdate"] =  new Date(2013, 1, 14, 0, 0, 0);
race["starters"][2]["horse"]["breedtype"] = "TB";
race["starters"][2]["horse"]["name"] = "Giant Expectations";
race["starters"][2]["horse"]["registry"] = "T";
race["starters"][2]["placepayoff"] = 0.0000;
race["starters"][2]["scratchindicator"] = false;
race["starters"][2]["showpayoff"] = 4.4000;
race["starters"][2]["owner"] = new Object();
race["starters"][2]["owner"]["identity"] = 2118116;
race["starters"][2]["owner"]["middlename"] = "";
race["starters"][2]["owner"]["lastname"] = "Exline-Border Racing LLC, Gatto Racing, LLC and Zubok, Garett";
race["starters"][2]["owner"]["firstname"] = "";
race["starters"][2]["owner"]["type"] = "O6";
race["starters"][2]["postposition"] = 2;
race["starters"][2]["trainer"] = new Object();
race["starters"][2]["trainer"]["identity"] = 531;
race["starters"][2]["trainer"]["middlename"] = "";
race["starters"][2]["trainer"]["lastname"] = "Eurton";
race["starters"][2]["trainer"]["firstname"] = "Peter";
race["starters"][2]["trainer"]["type"] = "TE";
race["starters"][2]["officialposition"] = 3;
race["starters"][2]["mutuelposition"] = 3;
race["starters"][2]["finishposition"] = 3;
race["starters"][2]["deadheat"] = false;
race["starters"][2]["sireofdamhorsename"] = "Is It True";
race["starters"][2]["winpayoff"] = 0.0000;
race["starters"][2]["jockey"] = new Object();
race["starters"][2]["jockey"]["identity"] = 117753;
race["starters"][2]["jockey"]["middlename"] = "R.";
race["starters"][2]["jockey"]["lastname"] = "Leparoux";
race["starters"][2]["jockey"]["firstname"] = "Julien";
race["starters"][2]["jockey"]["type"] = "JE";
race["starters"][2]["damhorsename"] = "Sarahisittrue";
race["starters"][3] = new Object();
race["starters"][3]["odds"] = 120;
race["starters"][3]["breedername"] = "";
race["starters"][3]["sirehorsename"] = "City Zip";
race["starters"][3]["disqualified"] = false;
race["starters"][3]["scratchreason"] = "";
race["starters"][3]["programnumber"] = "7";
race["starters"][3]["horse"] = new Object();
race["starters"][3]["horse"]["referencenumber"] = 9730945;
race["starters"][3]["horse"]["sex"] = "Gelding";
race["starters"][3]["horse"]["keenelandgrad"] = true;
race["starters"][3]["horse"]["foalingdate"] =  new Date(2014, 1, 24, 0, 0, 0);
race["starters"][3]["horse"]["breedtype"] = "TB";
race["starters"][3]["horse"]["name"] = "C Z Rocket";
race["starters"][3]["horse"]["registry"] = "T";
race["starters"][3]["placepayoff"] = 0.0000;
race["starters"][3]["scratchindicator"] = false;
race["starters"][3]["showpayoff"] = 0.0000;
race["starters"][3]["owner"] = new Object();
race["starters"][3]["owner"]["identity"] = 1200025;
race["starters"][3]["owner"]["middlename"] = "";
race["starters"][3]["owner"]["lastname"] = "Frank Fletcher Racing Operations, Inc.";
race["starters"][3]["owner"]["firstname"] = "";
race["starters"][3]["owner"]["type"] = "O6";
race["starters"][3]["postposition"] = 6;
race["starters"][3]["trainer"] = new Object();
race["starters"][3]["trainer"]["identity"] = 13572;
race["starters"][3]["trainer"]["middlename"] = "M.";
race["starters"][3]["trainer"]["lastname"] = "Stall, Jr.";
race["starters"][3]["trainer"]["firstname"] = "Albert";
race["starters"][3]["trainer"]["type"] = "TE";
race["starters"][3]["officialposition"] = 4;
race["starters"][3]["mutuelposition"] = 4;
race["starters"][3]["finishposition"] = 4;
race["starters"][3]["deadheat"] = false;
race["starters"][3]["sireofdamhorsename"] = "Successful Appeal";
race["starters"][3]["winpayoff"] = 0.0000;
race["starters"][3]["jockey"] = new Object();
race["starters"][3]["jockey"]["identity"] = 58000;
race["starters"][3]["jockey"]["middlename"] = "";
race["starters"][3]["jockey"]["lastname"] = "Bridgmohan";
race["starters"][3]["jockey"]["firstname"] = "Shaun";
race["starters"][3]["jockey"]["type"] = "JE";
race["starters"][3]["damhorsename"] = "Successful Sarah";
race["starters"][4] = new Object();
race["starters"][4]["odds"] = 370;
race["starters"][4]["breedername"] = "";
race["starters"][4]["sirehorsename"] = "Awesome Again";
race["starters"][4]["disqualified"] = false;
race["starters"][4]["scratchreason"] = "";
race["starters"][4]["programnumber"] = "1";
race["starters"][4]["horse"] = new Object();
race["starters"][4]["horse"]["referencenumber"] = 9466803;
race["starters"][4]["horse"]["sex"] = "Horse";
race["starters"][4]["horse"]["keenelandgrad"] = false;
race["starters"][4]["horse"]["foalingdate"] =  new Date(2013, 1, 6, 0, 0, 0);
race["starters"][4]["horse"]["breedtype"] = "TB";
race["starters"][4]["horse"]["name"] = "Awesome Slew";
race["starters"][4]["horse"]["registry"] = "T";
race["starters"][4]["placepayoff"] = 0.0000;
race["starters"][4]["scratchindicator"] = false;
race["starters"][4]["showpayoff"] = 0.0000;
race["starters"][4]["owner"] = new Object();
race["starters"][4]["owner"]["identity"] = 736381;
race["starters"][4]["owner"]["middlename"] = "";
race["starters"][4]["owner"]["lastname"] = "Live Oak Plantation";
race["starters"][4]["owner"]["firstname"] = "";
race["starters"][4]["owner"]["type"] = "O6";
race["starters"][4]["postposition"] = 1;
race["starters"][4]["trainer"] = new Object();
race["starters"][4]["trainer"]["identity"] = 20416;
race["starters"][4]["trainer"]["middlename"] = "E.";
race["starters"][4]["trainer"]["lastname"] = "Casse";
race["starters"][4]["trainer"]["firstname"] = "Mark";
race["starters"][4]["trainer"]["type"] = "TE";
race["starters"][4]["officialposition"] = 5;
race["starters"][4]["mutuelposition"] = 5;
race["starters"][4]["finishposition"] = 5;
race["starters"][4]["deadheat"] = false;
race["starters"][4]["sireofdamhorsename"] = "Seeking the Gold";
race["starters"][4]["winpayoff"] = 0.0000;
race["starters"][4]["jockey"] = new Object();
race["starters"][4]["jockey"]["identity"] = 2579;
race["starters"][4]["jockey"]["middlename"] = "J.";
race["starters"][4]["jockey"]["lastname"] = "Lanerie";
race["starters"][4]["jockey"]["firstname"] = "Corey";
race["starters"][4]["jockey"]["type"] = "JE";
race["starters"][4]["damhorsename"] = "Slewfoundmoney";
race["starters"][5] = new Object();
race["starters"][5]["odds"] = 880;
race["starters"][5]["breedername"] = "";
race["starters"][5]["sirehorsename"] = "Warrior\'s Reward";
race["starters"][5]["disqualified"] = false;
race["starters"][5]["scratchreason"] = "";
race["starters"][5]["programnumber"] = "4";
race["starters"][5]["horse"] = new Object();
race["starters"][5]["horse"]["referencenumber"] = 9731922;
race["starters"][5]["horse"]["sex"] = "Horse";
race["starters"][5]["horse"]["keenelandgrad"] = true;
race["starters"][5]["horse"]["foalingdate"] =  new Date(2014, 4, 9, 0, 0, 0);
race["starters"][5]["horse"]["breedtype"] = "TB";
race["starters"][5]["horse"]["name"] = "Warrior\'s Club";
race["starters"][5]["horse"]["registry"] = "T";
race["starters"][5]["placepayoff"] = 0.0000;
race["starters"][5]["scratchindicator"] = false;
race["starters"][5]["showpayoff"] = 0.0000;
race["starters"][5]["owner"] = new Object();
race["starters"][5]["owner"]["identity"] = 2074173;
race["starters"][5]["owner"]["middlename"] = "";
race["starters"][5]["owner"]["lastname"] = "Churchill Downs Racing Club";
race["starters"][5]["owner"]["firstname"] = "";
race["starters"][5]["owner"]["type"] = "O6";
race["starters"][5]["postposition"] = 3;
race["starters"][5]["trainer"] = new Object();
race["starters"][5]["trainer"]["identity"] = 1115;
race["starters"][5]["trainer"]["middlename"] = "Wayne";
race["starters"][5]["trainer"]["lastname"] = "Lukas";
race["starters"][5]["trainer"]["firstname"] = "D.";
race["starters"][5]["trainer"]["type"] = "TE";
race["starters"][5]["officialposition"] = 6;
race["starters"][5]["mutuelposition"] = 6;
race["starters"][5]["finishposition"] = 6;
race["starters"][5]["deadheat"] = false;
race["starters"][5]["sireofdamhorsename"] = "Citidancer";
race["starters"][5]["winpayoff"] = 0.0000;
race["starters"][5]["jockey"] = new Object();
race["starters"][5]["jockey"]["identity"] = 120381;
race["starters"][5]["jockey"]["middlename"] = "";
race["starters"][5]["jockey"]["lastname"] = "Landeros";
race["starters"][5]["jockey"]["firstname"] = "Chris";
race["starters"][5]["jockey"]["type"] = "JE";
race["starters"][5]["damhorsename"] = "Thirty Eighth St.";
race["nonbetting"] = false;
race["track"] = new Object();
race["track"]["identity"] = "CD";
race["track"]["country"] = "USA";
race["track"]["city"] = "Louisville";
race["track"]["state"] = "KY";
race["track"]["name"] = "CHURCHILL DOWNS";
race["name"] = "Ack Ack S.";
race["purse"] = 100000.0000;
race["purseenhancements"] = "";
race["agerestrictioncode"] = "3U";
race["date"] =  new Date(2018, 8, 29, 0, 0, 0);
race["maxclaim"] = 0.0000;
race["alternatevideosource"] = "";
race["sexrestriction"] = "Open";
race["cancelledindicator"] = "";
race["grade"] = "3";
race["agerestriction"] = "3 yo\'s & up";
race["posttime"] = "9:38";
race["sexrestrictioncode"] = " ";
;

            if("abrRaces" in window && abrRaces !== undefined && abrRaces.races.length > 0){
                var raceDate = new Date(race.date).setHours(0,0,0,0);

                for(var i=0; i < abrRaces.races.length; i ++){
                    var date = new Date(abrRaces.races[i].date.year, abrRaces.races[i].date.month-1, abrRaces.races[i].date.day, 0, 0, 0, 0).getTime();

                    if(raceDate === date && abrRaces.races[i].trackId === race.track.identity && abrRaces.races[i].country === race.track.country
                        && abrRaces.races[i].dayEvening === race.dayevening && abrRaces.races[i].raceNumber === race.number){

                        $("#abrRace").append('<img src =' + abrRaces.races[i].img + ' /><a href="' + abrRaces.races[i].link + '" >Coverage</a>').show();
                        break;
                    }
                }
            }
        });

        $(document).ready(function(){
            $("#replayVideo").on('shown.bs.modal', function(e){
                 openVideo();
            });
            $("#replayVideo").on('hide.bs.modal', function(e){
                stopJWVideo();
            });
            function stopJWVideo(){
                jwplayer("jwPlayerElement").remove();
            }
        });

        function openVideo () {

            var descriptionUrl = "https://www.equibase.com/";

            app.service.webYearbookRaces.getJWVideo(
                function (data) {

                    if (data.provider == 'P') {
                        var container = $('<div>').attr('class', 'playerContainer');

                        container.flash({
                            swf: '../premium/video/swf/videoplayer.swf' + data.flashParameters.streamAuth,
                            flashvars: {
                                appName: data.flashParameters.applicationName,
                                streamName: data.flashParameters.streamName
                            },
                            quality: 'high',
                            height: '394',
                            width: '480',
                            bgcolor: '#222222',
                            name: 'videoplayer',
                            align: 'middle',
                            allowScriptAccess: 'sameDomain',
                            allowFullScreen: true,
                            pluginsPage: 'http://www.macromedia.com/go/getflashplayer'
                        });
                    }

                    else if (data.provider == 'R'){
                        if(data.available){
                            var stream = data.stream;

                            jwplayer("jwPlayerElement").setup({
                                file: stream,
                                width: 640,
                                height: 480,
                                display: "inline-block",
                                autostart : true,
                                androidhls:true,
                                primary: "flash",
                                advertising : {
                                    client: "googima",
                                    tag:"https://pubads.g.doubleclick.net/gampad/ads?sz=640x480&iu=/2542414/equibase.com/video_pre-roll&impl=s&gdfp_req=1&env=vp&output=xml_vast2&unviewed_position_start=1&url=[referrer_url]&description_url=" + descriptionUrl + "&correlator=[timestamp]"
                                },
                                ga:{}
                            });
                        }
                    }
                },//The url beneath this comment are the parameters
            
                'CD',
                '2018-09-29',
                8,
                'D',
                'USA'
            
            );
        }


        function openChart () {
            var url = 'Chart.cfm?tk=CD&rd=2018-09-29&rn=8&de=D&cy=USA';
            var title = '';
            var options = 'height=800, width=600, channelmode=no, directories=no, fullscreen=no, location=no, menubar=no, resizable=yes, scrollbars=no, status=no, titlebar=no, toolbar=no';

            window.open(url, title, options);
        }
    </script>
<style>
/*this makes it so that JW player doesn't crash older browsers on ipad*/
.jwplayer { -webkit-overflow-scrolling: auto; }
</style>
    <!-- HEADER -->
    <div class="row">
        <div class="col-xs-12">
            <h1>Equibase Racing Yearbook</h1>
            <div id="addThis" class="phone-hide">
	<a title="Print Screen" alt="Print Screen" onclick="window.print();" target="_blank" style="cursor:pointer;">
		<img border="0" src="/images/prient_icon.jpg">
	</a>
</div>


        </div>
    </div>
</section>
    <!-- END HEADER -->

<!-- INTERIOR CONTENT AREA -->
<section id="contentwrapper" class="l-section">
    <div class="row">
        <div class="col-xs-12 col-md-8 col-lg-9">
            <div class="interior-content">
                <div class="component" id="c-shop-pps">
            <div class="content">
                    <!-- CONTENT GOES BELOW HERE -->

                


                             <!--2018 <img src="/images/logos/abr-md.gif">-->


                        <h2 class="paddingtop15 lightgreentxt">
                     <center><br>
                        
                            <a href="/profiles/Results.cfm?type=Stakes&stkid=2413">ACK ACK S. - GR. 3 </a>
                        
                        </center>
                    </h2>

                    <center><h2  class="paddingtop15 lightgreentxt"><a href="/profiles/Results.cfm?type=Track&trk=CD&cy=USA">Churchill Downs</a> - September 29, 2018 - Race 8</h5>
                    </center>
                    <div id="videoPlayer" title="ACK ACK S. - GR. 3"></div>

                    <ul class="yearbook header">
                    
                        <li><img src="/images/products/video.gif" border="0" /><a href="#" class="replayVideoLink" data-toggle="modal" data-target="#replayVideo">Replay</a></li>
                    
                        <li><img src="/images/products/pdf-icon.png" border="0" /> <a  href="javascript:openChart()">Result Chart</a></li>
                        <li id="abrRace" style="display:none"></li>
                    </ul>

                    <ul class="yearbook">
                        <li><B>Race Name:</B> Ack Ack S. - <B>Grade:</B> 3</li>
                        <li><B>Off at:</B> 9:38</li>
                        <li><B>Race Type:</B> Stakes</li>
                        <li><B>Age Restriction:</B> 3 yo's & up</li>
                        <li><B>Sex Restriction:</B> Open</li>
                        <li><B>Purse:</B> $100,000</li>
                        <li><B>Distance:</B> One Mile</li>
                        <li><B>Track Condtion:</B> Fast</li>
                        <li><B>Winning Time:</B> 1:35.01</li>
                    </ul>

                    <table class="text-left">
                        <thead>
                            <tr>
                                <th>Pgm</th>
                                <th>Horse</th>
                                <th>Jockey</th>
                                <th class="right-align">Win</th>
                                <th class="right-align">Place</th>
                                <th class="right-align">Show</th>
                            </tr>
                        </thead>
                        <tbody>
                            
                                <tr>
                                    <td>6</td>
                                    <td><a href="/profiles/Results.cfm?type=Horse&refno=9512495&registry=T">Seeking the Soul</a></td>
                                    <td><a href="/profiles/Results.cfm?type=People&searchType=J&eID=109036"> Brian Joseph Hernandez, Jr. </a></td>
                                    <td class="right-align">$9.20</td>
                                    <td class="right-align">$5.20</td>
                                    <td class="right-align">$3.40</td>
                                </tr>
                            
                                <tr>
                                    <td>5</td>
                                    <td><a href="/profiles/Results.cfm?type=Horse&refno=9755573&registry=T">Nice Not Nice</a></td>
                                    <td><a href="/profiles/Results.cfm?type=People&searchType=J&eID=121307"> Gabriel  Saez </a></td>
                                    <td></td>
                                    <td colspan="1" class="right-align">$12.60</td>
                                    <td class="right-align">$4.80</td>
                                </tr>
                            
                                <tr>
                                    <td>2</td>
                                    <td><a href="/profiles/Results.cfm?type=Horse&refno=9526657&registry=T">Giant Expectations</a></td>
                                    <td><a href="/profiles/Results.cfm?type=People&searchType=J&eID=117753"> Julien R. Leparoux </a></td>
                                    <td></td>
                                    <td></td>
                                    <td colspan="1" class="right-align">$4.40</td>
                                </tr>
                            
                        </tbody>
                    </table>

                    <ul class="yearbook">
                        
                            <li><strong>Also Ran:</strong> 7 - C Z Rocket, 1 - Awesome Slew, 4 - Warrior's Club</li>
                        
                            <li><strong>Scratched Horses:</strong> Flatlined (Trainer)</li>
                        
                    </ul>

                    <table class="text-left table-padded" >
                        <thead>
                            <tr>
                                <th>Wager Type</th>
                                <th>Winning Numbers</th>
                                <th class="right-align">Payoff</th>
                            </tr>
                        </thead>
                        <tbody>
                            
                                <tr>
                                    <td>Pick 3</td>
                                    <td>7-5-6</td>
                                    <td class="right-align">$85.30</td>
                                </tr>
                            
                                <tr>
                                    <td>Daily Double</td>
                                    <td>5-6</td>
                                    <td class="right-align">$18.30</td>
                                </tr>
                            
                                <tr>
                                    <td>Exacta</td>
                                    <td>6-5</td>
                                    <td class="right-align">$179.00</td>
                                </tr>
                            
                                <tr>
                                    <td>Superfecta</td>
                                    <td>6-5-2-7</td>
                                    <td class="right-align">$58.51</td>
                                </tr>
                            
                                <tr>
                                    <td>Trifecta</td>
                                    <td>6-5-2</td>
                                    <td class="right-align">$146.15</td>
                                </tr>
                            
                        </tbody>
                    </table>

                        

                    <ul class="yearbook">
                        <li><strong>Winning Breeder:</strong> Charles Fipke</li>
                        <li><strong>Winning Owner:</strong><a href="/profiles/Results.cfm?type=People&searchType=O&eID=786617"> Charles E. Fipke</a></li>
                        <li><strong>Winning Trainer:</strong><a href="/profiles/Results.cfm?type=People&searchType=T&eID=135878"> Dallas  Stewart</a></li>
                    </ul>

    


    
    <div class="modal fade" id="replayVideo" tabindex="-1" role="dialog" aria-labelledby="myModalLabel" aria-hidden="true" data-urlLink="#myVideoLink#" data-jwStreams='#jwSerialized#' >
        <div class="modal-dialog" style="width:670px">
            <div class="modal-content">
                <div class="modal-header">
                    <button type="button" class="close" data-dismiss="modal" aria-hidden="true">&times;</button>
                    <h4 class="modal-title" id="replayVideoLabel">Video Replay</h4>
                </div>
                <div class="modal-body" id="videoPlayer" style="text-align:center;">
                    <div style="display:inline-block">
                        <div id="jwPlayerElement" style="display:inline-block"></div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-default" data-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    </div>


                    <!-- END OF CONTENT DIV -->
            </div>


            </div>
        </div>
    </div>
    <!-- END INTERIOR CONTENT AREA -->

<!-- AD AND SIDEBAR AREA -->
    <div class="sidebar col-xs-12 col-md-4 col-lg-3">
        
        		   		<!-- AD AND SIDEBAR AREA -->

			<div id="anchorDiv"></div>
<div id="stickyDiv">
	<!-- /2542414/EQ_Desktop_ROS_300x250_ATF_Sidebar1 -->
	<div id='adDiv1' data-fuse="EQ_Desktop_ROS_300x250_ATF_Sidebar1" class='adunit ad--no-overflow-300x'>

	</div>
</div>

<div id="internal-adspace" class="component spaced box-b homepage-module-divider">
</div>

<div id="sidebar-video-desktop" data-fuse="EQ_Sidebar_Video_Desktop">

</div>


<script type="text/javascript" src="/js/stickyAds.js?v=1.6"></script>


<!-- end: sidebar test-->
			

	<!-- END AD AND SIDEBAR AREA -->
    </div>
</div>
</section>
<!-- END AD AND SIDEBAR AREA -->

   
            <!-- FOOTER -->

            <!-- Google Code for Remarketing tag -->
            <!-- Remarketing tags may not be associated with personally identifiable information or placed on pages related to sensitive categories. For instructions on adding this tag and more information on the above requirements, read the setup guide: google.com/ads/remarketingsetup -->
            
            
            <script type="text/plain" class="optanon-category-C0004">
                /* <![CDATA[ */
                var google_conversion_id = 1003127189;
                var google_conversion_label = "YvN3CLvTngQQlYOq3gM";
                var google_custom_params = window.google_tag_params;
                var google_remarketing_only = true;
                /* ]]> */
            </script>
            <script type="text/plain" class="optanon-category-C0004" src="https://www.googleadservices.com/pagead/conversion.js"></script>
            <noscript>
                <div style="display:inline;">
                    <img height="1" width="1" style="border-style:none;" alt="" src="https://googleads.g.doubleclick.net/pagead/viewthroughconversion/1003127189/?value=0&amp;label=YvN3CLvTngQQlYOq3gM&amp;guid=ON&amp;script=0"/>
                </div>
            </noscript>

            <!-- BEGIN FOOTER SECTION -->
            <section id="footer" class="l-section">
                <div class="row">
                    <div class="col-xs-12">
                        <!-- footer links -->
                        <div class="footer-links clearfix hidden-print" style="padding: 10px 0px 0px 0px;">
                            <ul>
                                <li><a href="/sitemap.cfm">Site Map</a></li>
                                <li><a href="/about/about.cfm">About Us</a></li>
                                <li><a href="/about/privacypolicy.cfm">Privacy Policy</a></li>
                                <li><a href="/about/contact.cfm">Contact Us</a></li>
                            </ul>
                            <ul>
                                <li><a href="/about/faq.cfm">F.A.Q.</a></li>
                                <li><a href="https://media.equibase.com/">Advertising</a></li>
                                <li><a href="/about/terms.cfm">Terms of Use</a></li>
                                <li><a href="/products/handicapperstore.cfm">Price List</a></li>
                            </ul>
                        </div>
                        <div> <!-- Marketplace footer links styled for desktop vs. mobile -->
                            <div class="phone-hide tablet-show desktop-show">
                                
<!-- begin: marketplace footer block-->


    <div class="row" style="padding: 0px 0px 20px 0px; background-color:#015739;">
        <div class="l-section-inner col-xs-12" style="padding: 10px 20px 5px 20px;">
            <div class="row footer-marketplace">
                <div class="col-xs-12 col-xs-3"  style="width: 230px">
					
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Account Wagering</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5636253020&iu=/2542414/EQ_Click_Marketplace/MPL_1stBet"> 1/ST BET</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4504732726&iu=/2542414/EQ_Click_Marketplace/MPL_AmWest"> AmWager</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6194213975&iu=/2542414/EQ_Click_Marketplace/MPL_TVG"> FanDuel Racing </a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5881138986&iu=/2542414/EQ_Click_Marketplace/MPL_NYRA"> NYRA Bets</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4686048668&iu=/2542414/EQ_Click_Marketplace/MPL_TwinSpires"> TwinSpires</a>
											</div>
										
							
							</div>
							
								<div class="col-xs-3" style="width: 230px">
							
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Associations</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6195889164&iu=/2542414/EQ_Click_Marketplace/MPL_BreedersCup"> Breeders' Cup World Championships</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5644147392&iu=/2542414/EQ_Click_Marketplace/MPL_HPBA"> National HBPA</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6195836633&iu=/2542414/EQ_Click_Marketplace/MPL_NYTBDF"> New York Thoroughbred Breeding & Development Fund</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Bloodstock Agents</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6194170499&iu=/2542414/EQ_Click_Marketplace/MPL_BradleyThoroughbreds/Bloodstock"> Bradley Thoroughbreds LLC</a>
											</div>
										
							
							</div>
							
								<div class="col-xs-3" style="width: 230px">
							
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Equine Products</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="https://www.bigdweb.com/category/thoroughbred+racing.do?code=EQUIBASE"> Big Dee's Tack & Vet Supplies</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6527277769&iu=/2542414/EQ_Click_Marketplace/MPL_OCDPellets"> OCD Pellets/Doc's Products Inc.</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Handicapping Products</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5617683774&iu=/2542414/EQ_Click_Marketplace/Thorograph"> Thoro-graph</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5091716864&iu=/2542414/EQ_Click_Marketplace/MPL_TrackWiz"> TrackWiz Mobile App</a>
											</div>
										
							
							</div>
							
								<div class="col-xs-3" style="width: 230px">
							
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Publications</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4965912170&iu=/2542414/EQ_Click_Marketplace/MPL_BloodHorse"> BloodHorse</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5626235913&iu=/2542414/EQ_Click_Marketplace/MPL_TDN"> TDN</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Racetracks</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=7260172305&iu=/2542414"> Delaware Park</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=7213049964&iu=/2542414/EQ_Click_TLProfiles/EQ_Click_TLProfiles_MTH"> Racing from the Jersey Shore</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Racing News</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="https://www.americasbestracing.net?sap=marketplace"> America's Best Racing</a>
											</div>
										
							
							</div>
							
								<div class="col-xs-3" style="width: 230px">
							
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Racing Partnerships</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6194171219&iu=/2542414/EQ_Click_Marketplace/MPL_BradleyThoroughbreds/Partnership"> Bradley Thoroughbreds</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4507748784&iu=/2542414/EQ_Click_Marketplace/MPL_CentennialFarm"> Centennial Farms</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=7164263968&iu=/2542414/EQ_Click_Marketplace/MPL_MorningLine"> MORNINGLINE.io</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5412430554&iu=/2542414/EQ_Click_Marketplace/MPL_PewterStables"> Pewter</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4511166624&iu=/2542414/EQ_Click_Marketplace/MPL_PocketAcesRacing"> Pocket Aces Racing</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4511171463&iu=/2542414/EQ_Click_Marketplace/MPL_TeamValor"> Team Valor</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4511190414&iu=/2542414/EQ_Click_Marketplace/MPL_WestPointThoroughbreds"> West Point Thoroughbreds</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Sales</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=7241653918&iu=/2542414/EQ_Click_Marketplace/MPL_Keeneland"> Keeneland April Sale</a>
											</div>
										
							
							</div>
							
				</div>
			</div>
		</div>
	</div>
    <!-- end: marketplace footer block -->
                            </div>
                            <div class="phone-show tablet-hide desktop-hide">
                                
<!-- begin: marketplace footer block-->


    <div class="row" style="padding: 0px 0px 20px 0px; background-color:#015739;">
        <div class="l-section-inner col-xs-12" style="padding: 10px 20px 5px 20px;">
            <div class="row footer-marketplace">
                <div class="col-xs-12 col-xs-3"  style="width: 230px">
					
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Account Wagering</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5636253020&iu=/2542414/EQ_Click_Marketplace/MPL_1stBet"> 1/ST BET</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4504732726&iu=/2542414/EQ_Click_Marketplace/MPL_AmWest"> AmWager</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6194213975&iu=/2542414/EQ_Click_Marketplace/MPL_TVG"> FanDuel Racing </a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5881138986&iu=/2542414/EQ_Click_Marketplace/MPL_NYRA"> NYRA Bets</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4686048668&iu=/2542414/EQ_Click_Marketplace/MPL_TwinSpires"> TwinSpires</a>
											</div>
										
							
							</div>
							
								<div class="col-xs-3" style="width: 230px">
							
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Associations</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6195889164&iu=/2542414/EQ_Click_Marketplace/MPL_BreedersCup"> Breeders' Cup World Championships</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5644147392&iu=/2542414/EQ_Click_Marketplace/MPL_HPBA"> National HBPA</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6195836633&iu=/2542414/EQ_Click_Marketplace/MPL_NYTBDF"> New York Thoroughbred Breeding & Development Fund</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Bloodstock Agents</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6194170499&iu=/2542414/EQ_Click_Marketplace/MPL_BradleyThoroughbreds/Bloodstock"> Bradley Thoroughbreds LLC</a>
											</div>
										
							
							</div>
							
								<div class="col-xs-3" style="width: 230px">
							
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Equine Products</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="https://www.bigdweb.com/category/thoroughbred+racing.do?code=EQUIBASE"> Big Dee's Tack & Vet Supplies</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6527277769&iu=/2542414/EQ_Click_Marketplace/MPL_OCDPellets"> OCD Pellets/Doc's Products Inc.</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Handicapping Products</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5617683774&iu=/2542414/EQ_Click_Marketplace/Thorograph"> Thoro-graph</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5091716864&iu=/2542414/EQ_Click_Marketplace/MPL_TrackWiz"> TrackWiz Mobile App</a>
											</div>
										
							
							</div>
							
								<div class="col-xs-3" style="width: 230px">
							
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Publications</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4965912170&iu=/2542414/EQ_Click_Marketplace/MPL_BloodHorse"> BloodHorse</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5626235913&iu=/2542414/EQ_Click_Marketplace/MPL_TDN"> TDN</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Racetracks</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=7260172305&iu=/2542414"> Delaware Park</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=7213049964&iu=/2542414/EQ_Click_TLProfiles/EQ_Click_TLProfiles_MTH"> Racing from the Jersey Shore</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Racing News</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="https://www.americasbestracing.net?sap=marketplace"> America's Best Racing</a>
											</div>
										
							
							</div>
							
								<div class="col-xs-3" style="width: 230px">
							
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Racing Partnerships</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=6194171219&iu=/2542414/EQ_Click_Marketplace/MPL_BradleyThoroughbreds/Partnership"> Bradley Thoroughbreds</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4507748784&iu=/2542414/EQ_Click_Marketplace/MPL_CentennialFarm"> Centennial Farms</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=7164263968&iu=/2542414/EQ_Click_Marketplace/MPL_MorningLine"> MORNINGLINE.io</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=5412430554&iu=/2542414/EQ_Click_Marketplace/MPL_PewterStables"> Pewter</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4511166624&iu=/2542414/EQ_Click_Marketplace/MPL_PocketAcesRacing"> Pocket Aces Racing</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4511171463&iu=/2542414/EQ_Click_Marketplace/MPL_TeamValor"> Team Valor</a>
											</div>
										
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=4511190414&iu=/2542414/EQ_Click_Marketplace/MPL_WestPointThoroughbreds"> West Point Thoroughbreds</a>
											</div>
										
								<h5 class="lightgoldtxt" style="margin: 15px 0px 5px 0px">Sales</h5>
									
											<div>
												<a style="color:white;" target="_blank" href="http://pubads.g.doubleclick.net/gampad/clk?id=7241653918&iu=/2542414/EQ_Click_Marketplace/MPL_Keeneland"> Keeneland April Sale</a>
											</div>
										
							
							</div>
							
				</div>
			</div>
		</div>
	</div>
    <!-- end: marketplace footer block -->
                            </div>
                        </div>

                        <!-- end footer links -->

                        <!-- company info / accepted payments -->
                        <div class="row companyinfo hidden-print">
                            <div class="col-xs-12 col-sm-9">
								<p>
                                    Equibase Company is the Official Supplier of Racing Information and Statistics to <a target="_blank" href="http://www.followhorseracing.com">America's Best Racing</a>, <a target="_blank" href="http://www.breederscup.com">Breeders' Cup</a>, <a target="_blank" href="https://www.brisnet.com/racing/">BRISnet</a>, <a target="_blank" href="http://www.drf.com">Daily Racing Form</a>, <a href="https://racing.fanduel.com/">FanDuel Racing</a>, <a href="http://www.ntra.com">NTRA</a>, <a target="_blank" href="http://www.thejockeyclub.com">The Jockey Club</a>, <a target="_blank" href="https://thoroughbredracingassociations.com/">TRA</a>, <a target="_blank" href="https://www.twinspires.com/">TwinSpires</a>, and <a target="_blank" href="http://1st.com/bet">1/ST</a>.
                                </p>
                            </div>

                        </div>
                        <!-- end company info/accepted payments -->

                        <!-- legal -->
                        <div class="legal">
                            Proprietary to and &copy; 2026 Equibase Company LLC. All Rights Reserved.<br>
                            The Terms of Use for this web site prohibit the use of any robot, spider, scraper or any other automated means to access the contents of this site. The Terms of Use also expressly prohibit the republication or dissemination of the contents of this screen without the prior written consent of Equibase Company LLC.<br>
                            <br>
                            <a class="optanon-show-settings legal"><img src="/images/privacyoptions.png" alt="Privacy Options" style="width: 50px;padding-right: 10px">Your Privacy Choices</a>
                        </div>
                        <!-- end legal -->
                    </div>
                </div>
            </section>
            <!-- END FOOTER SECTION -->
        </div>

        

        <script src="/bundles/scripts-footer.js?v=20260611"></script>
        <script>
            $('.showHelp').click(function() {
                $('body').chardinJs('start');
                return false;
            });

            $('body').popover({
                selector: '[rel=popover]'
            });
            // handle the ios zoom issue with select boxes (prevent zooming in on them)
            $('select').mousedown(function(){
                $('meta[name=viewport]').remove();
                $('head').append('<meta name="viewport" content="width=device-width, maximum-scale=1.0, user-scalable=0">');
            })
            // and when the select no longer has focus put things back as they were
            $('select').focusout(function(){
                $('meta[name=viewport]').remove();
                $('head').append('<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">' );
            })

            $(document).ready(function(){
                if (app.cookie && app.cookie.get("PAC") !== "" && app.cookie.get("PAC") !== null || (getCookie("PAC") != "")){
                    $(".account-logged-in").show();
                } else {
                    $(".account-login").show();
                }
            });
        </script>


        <script type="text/javascript" src="/js/lazySizes.js?v=5.2.0"></script>
    <script type="text/javascript" src="/_Incapsula_Resource?SWJIYLWA=719d34d31c8e3a6e6fffd425f7e032f3&ns=1&cb=1203508013" async></script></body>
</html> 