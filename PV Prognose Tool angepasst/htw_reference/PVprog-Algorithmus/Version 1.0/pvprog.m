function [a,v,pf,eb,soc]=pvprog(time,p_pv,P_ld,bs,P_stc,C_bu,P_bwr,p_gfl)
 
%% PVprog-Algorithmus 
% 
% Algorithmus zur Umsetzung der prognosebasierten Batterieladung für
% PV-Speichersysteme mit messwertbasierten PV- und Lastprognosen
%
% Autoren: J. Bergner, J. Weniger, T. Tjaden,
% Forschungsgruppe Solarspeichersysteme,
% Hochschule für Technik und Wirtschaft HTW Berlin
%
% Version: 1.0 (4/2016)
%
% Inhalt: Dieser Programm-Code ermöglicht einminütige Simulationsrechnungen
% von PV-Speichersystemen mit zwei unterschiedlichen Betriebsstrategien
% über den Zeitraum von einem Jahr in der Programmierumgebung MATLAB. Im
% Fokus steht dabei der Vergleich folgender Batterieladestrategien:
% 
% (1) Frühzeitige Batterieladung: Der Batteriespeicher wird möglichst
% schnell geladen, sofern überschüssige PV-Energie vorhanden ist.
%
% (2) Prognosebasierte Batterieladung: Der Batteriespeicher wird unter
% Berücksichtigung von Last- und PV-Prognosen nur oberhalb einer virtuell
% festgelegten Einspeisegrenze geladen. Dadurch lässt sich ein
% eigenversorgungs- und netzoptimierter Einsatz der PV-Speichersysteme
% erzielen. Somit kann die geforderte 50%-Einspeisebegrenzung des
% KfW-Speicherförderprogramms und eine hohe Eigenversorgung realisiert
% werden.
%
% Nutzen: Die Vorteile der prognosebasierten Betriebsstrategie gegenüber
% der frühzeitigen Batterieladung wurden in der 50%-Studie (Effekte der
% 50%-Einspeisebegrenzung des KfW-Förderprogramms für
% Photovoltaik-Speichersysteme) der HTW Berlin ausführlich beschrieben.
%
% https://pvspeicher.htw-berlin.de/50prozent-studie/
%
% Zitation: Bei vollständiger oder teilweiser Verwendung des Algorithmus
% bitte wie folgt auf den Programm-Code verweisen:
%
% J. Bergner, J. Weniger, T. Tjaden : PVprog-Algorithmus - Algorithmus zur
% Umsetzung der prognosebasierten Batterieladung für PV-Speichersysteme mit
% messwertbasierten PV- und Lastprognosen (Version 1.0). Berlin: Hochschule
% für Technik und Wirtschaft HTW Berlin, 2016
%
% Hinweis: Zur Ausführung des PVprog-Algorithmus das Skript run_pvprog.m
% nutzen.

%% Struktur des Programm-Codes
%
% Der Programm-Code setzt sich aus zahlreichen Befehlen und Unterfunktionen
% zusammen und ist wie folgt strukturiert (die Namen der Unterfunktionen
% sind in Klammern angegeben):
%
% 1. Frühzeitige Batterieladung
%
% 1.1 Batteriesimulation (batt_sim)
%
% 1.2 Auswertung der Simulationsergebnisse (simu_erg)
%
% 2. Prognosebasierte Batterieladung
%
% 2.1 Erstellung der Prognosen
%
% 2.1.1 PV-Prognose (prog4pv)
%
% 2.1.2 Lastprognose (prog4ld)
%
% 2.2 Umsetzung der prognosebasierten Ladestrategie
%
% 2.2.1 Batterieladeplanung über den Prognosehorizont (batt_prog)
%
% 2.2.2 Ausregelung von Prognosefehlern (error_ctrl)
%
% 2.2.3 Batteriesimulation (batt_sim)
%
% 2.3 Auswertung der Simulationsergebnisse (simu_erg)

%% Hintergrundinformationen zum Algorithmus und Simulationsmodell
%
% a) Prognosebasierte Batterieladestrategie
%
% Grundsätzlich existieren unterschiedliche Ansätze, um eine
% prognosebasierte Betriebsführung von PV-Speichersystemen zu realisieren
% [Sie15]. Ziel solcher Betriebsstrategien ist es, neben einer hohen
% Eigenversorgung zugleich die Begrenzung der Einspeiseleistung mit dem
% Batteriespeicher zu ermöglichen. Durch die zeitliche Verschiebung der
% Batterieladung in die Mittagszeit sollen somit Abregelungsverluste
% vermieden werden. Hierzu bedarf es einer vorausschauenden Planung der
% Batterieladung über den Tag unter Berücksichtigung von Prognosen.
%
% Die Grundlage stellen standortspezifische Prognosen der PV-Erzeugung und
% des Stromverbrauchs der nächsten Stunden dar. Idealerweise sollte der
% Prognosehorizont mindestens der Zeitspanne zwischen dem Sonnenaufgang und
% -untergang entsprechen. Haushaltsspezifische Lastprognosen werden in der
% Regel auf Basis von historischen Messdaten erstellt [Wen15]. Der Verlauf
% der PV-Leistung in den folgenden Stunden lässt sich in erster Näherung
% durch messwertbasierte Prognoseansätze bestimmen, deren Prognosegüte für
% die Batterieladeplanung oftmals hinreichend genau ist [Ber14a].
%
% Auf Grundlage der Prognosen und des momentanen Batterieladezustands wird
% zunächst ein optimaler Fahrplan für die Batterieladung über den gesamten
% Prognosehorizont erstellt. Die Batterieladeoptimierung lässt sich
% mathematisch durch einen linearen Optimierungsalgorithmus oder iterativ
% lösen [Ber14a, Wen13]. In diesem Programm-Code wird der iterative Ansatz
% verfolgt, mit dem über den jeweiligen Prognosehorizont eine virtuelle
% Einspeisegrenze bestimmt. Dabei wird die virtuelle Einspeisegrenze
% schrittweise herabgesetzt, bis der Batteriespeicher sich mit der
% Energiemenge oberhalb dieser Grenze möglichst vollständig laden lässt.
% Daraus lässt sich im Anschluss für jeden Zeitschritt des
% Prognosezeitraums die zur Kappung der Einspeisespitze erforderliche
% Ladeleistung bestimmen.
%
% Aufgrund von Prognosefehlern muss die ermittelte optimale Ladeleistung
% kontinuierlich an die tatsächlichen Leistungsmesswerte angepasst werden.
% Durch eine nachgelagerte Regelung wird die aktuelle Ladeleistung daher
% um die Differenz zwischen den aktuellen Prognose- und Messwerten
% korrigiert [Ber14b]. Die dadurch korrigierte Ladeleistung kann dem
% Batteriespeicher als Sollwertvorgabe übergeben werden. Durch die
% Korrektur der Ladeleistung kommt es im Vergleich zum ursprünglichen
% Fahrplan allerdings zu Abweichungen im Batterieladezustand. Daher sollte
% die Batterieladeplanung auf Basis des geänderten Ladezustands in
% regelmäßigen Abständen, beispielsweise in einem Intervall von 15 min,
% aktualisiert werden. Durch die fortlaufende Aktualisierung des
% Ladefahrplans können zudem aktualisierte PV- und Lastprognosen
% Berücksichtigung finden.
%
% b) Simulationsmodell des Batteriespeichers
%
% Die Modellierung des AC-gekoppelten Lithium-Ionen-Batteriespeichers
% erfolgt mit einem einfachen Modell, das in [Wen13] näher beschrieben ist.
% Die Wandlungsverluste der Batteriezellen werden dabei mit einem mittleren
% Energiewirkungsgrad von 95% veranschlagt. Der Wirkungsgrad des
% Batteriewechselrichters wird als konstant angenommen und mit 94%
% angesetzt. Der mittlere Gesamtwirkungsgrad des modellierten
% Batteriespeichersystems liegt somit bei rund 84%. Die Leistungsaufnahme
% und -abgabe des Batteriespeichersystems wird durch die vorgegenene
% Nennleistung des Batteriewechselrichters beschränkt.
%
% Quellen:
%
% [Ber14a] 	J. Bergner: Untersuchungen zu prognosebasierten
% Betriebsstrategien für PV-Speichersysteme. Berlin, Hochschule für Technik
% und Wirtschaft Berlin, Bachelorthesis, 2014
%
% [Ber14b] 	J. Bergner, J. Weniger, T. Tjaden, V. Quaschning: Feed-in Power
% Limitation of Grid-Connected PV Battery Systems with Autonomous
% Forecast-Based Operation Strategies. In: 29th European Photovoltaic Solar
% Energy Conference and Exhibition. Amsterdam, 2014
%
% [Sie15] 	B. Siegel, J. Bergner: Betriebsstrategien für
% PV-Speichersysteme im Vergleich. Berlin, Hochschule für Technik und
% Wirtschaft Berlin, Projektarbeit, 2015
%
% [Wen13] J. Weniger, V. Quaschning: Begrenzung der Einspeiseleistung von
% netzgekoppelten Photovoltaiksystemen mit Batteriespeichern. In: 28.
% Symposium Photovoltaische Solarenergie. Bad Staffelstein, 2013
%
% [Wen15] 	J. Weniger, J. Bergner, T. Tjaden, V. Quaschning: Dezentrale
% Solarstromspeicher für die Energiewende. 1. Aufl. Berlin: Berliner
% Wissenschafts-Verlag, 2015 — ISBN 978-3-8305-3548-5

%% Hinweise
%
% a) Einminütige Simulationszeitschrittweite erforderlich: 
% Der Programm-Code ist für die Durchführung von Simulationen mit
% Zeitreihen der PV-Leistung und elektrischen Last über einen Zeitraum von
% 365 Tagen erstellt worden. Die Simulationszeitschrittweite beträgt 1 min.
% Für andere Zeitschrittweiten und Zeiträume müssen Änderungen im
% Programm-Code vorgenommen werden.
%
% b) Batteriespeichermodell hat beschränkten Detailierungsgrad:
% Da die Veröffentlichung des vorliegenden Programm-Codes auf die
% Verbreitung von prognosebasierten Ladestrategien abzielt, wurde ein
% Batteriemodell mit geringem Programmierungs- und Parametrisierungsaufwand
% implementiert. Das simulierte Lade- und Entladeverhalten des
% Batteriespeichers kann sich daher von der Charakteristik realer
% Speichersysteme unterscheiden.
%
% c) Programm-Code ermöglicht in der vorliegenden Form keine
% Echtzeitregelung von Speichern: 
% Der vorliegende Programm-Code dient zur Ausführung von
% Zeitschrittsimulationen. Um den Programm-Code in Echtzeit zur Regelung
% von Speichersystemen einzusetzen, sind Anpassungen vorzunehmen. Der
% Programm-Code ist ausführlich kommentiert und kann für eigene Anwendungen
% und zum Einsatz in Energiemanagement-Systemen genutzt werden. Dies ist
% ausdrücklich erwünscht. Die Autoren können jedoch nicht bei der
% Implentierung des Algorithmus unterstützen und keinen Support bei
% Problemen mit der Programm-Ausführung geben. Im Forschungsprojekt
% "PVprog: Entwicklung von prognosebasierten Betriebsstrategien für
% PV-Speichersysteme" wurde die praktische Realisierbarkeit der
% Echtzeitsteuerung mit dem beschriebenen Algorithmus nachgewiesen.
%
% d) Programm-Code enthält Befehle, die in älteren Matlab-Releases nicht
% verfügbar sind: 
% Der Programm-Code wurde in der Matlab-Version R2015b entwickelt und
% enthält Befehle, die in älteren Versionen noch nicht implementiert sind.
% Dadurch können Probleme bei der Ausführung des Programm-Codes mit älteren
% Matlab-Versionen auftreten.

%% Lizenzierung
%
% MIT-Lizenz
% 
% Copyright (c) 2016 Joseph Bergner, Johannes Weniger, Tjarko Tjaden
% 
% Hiermit wird unentgeltlich jeder Person, die eine Kopie der Software und
% der zugehörigen Dokumentationen (die "Software") erhält, die Erlaubnis
% erteilt, sie uneingeschränkt zu nutzen, inklusive und ohne Ausnahme mit
% dem Recht, sie zu verwenden, zu kopieren, zu verändern, zusammenzufügen,
% zu veröffentlichen, zu verbreiten, zu unterlizenzieren und/oder zu
% verkaufen, und Personen, denen diese Software überlassen wird, diese
% Rechte zu verschaffen, unter den folgenden Bedingungen:
% 
% Der obige Urheberrechtsvermerk und dieser Erlaubnisvermerk sind in allen
% Kopien oder Teilkopien der Software beizulegen.
% 
% DIE SOFTWARE WIRD OHNE JEDE AUSDRÜCKLICHE ODER IMPLIZIERTE GARANTIE
% BEREITGESTELLT, EINSCHLIESSLICH DER GARANTIE ZUR BENUTZUNG FÜR DEN
% VORGESEHENEN ODER EINEM BESTIMMTEN ZWECK SOWIE JEGLICHER
% RECHTSVERLETZUNG, JEDOCH NICHT DARAUF BESCHRÄNKT. IN KEINEM FALL SIND DIE
% AUTOREN ODER COPYRIGHTINHABER FÜR JEGLICHEN SCHADEN ODER SONSTIGE
% ANSPRÜCHE HAFTBAR ZU MACHEN, OB INFOLGE DER ERFÜLLUNG EINES VERTRAGES,
% EINES DELIKTES ODER ANDERS IM ZUSAMMENHANG MIT DER SOFTWARE ODER
% SONSTIGER VERWENDUNG DER SOFTWARE ENTSTANDEN.

%% Förderung
%
% Der vorliegende Programm-Code ist in folgenden Forschungsprojekten
% entstanden:
%
% PVprog: Entwicklung von vorhersagebasierten Betriebsstrategien für
% Photovoltaik-Batteriesysteme zur verbesserten Systemintegration der
% Photovoltaik (Förderkennzeichen 11410 UEP II/2)
%
% LAURA/PVstore: Verbundvorhaben: Langlebige Qualitätsmodule für PV-Systeme
% mit Speicheroption und intelligentem Energiemanagement (LAURA)
% Teilvorhaben: Energiemanagement und Optimierung von Photovoltaiksystemen
% mit Batterie- und Wärmespeichern (PVstore) (Förderkennzeichen: 0325716G)

%% Wesentliche verwendete Variablen

% a:        Autarkiegrad
% bs:       Betriebsstrategie (1: frühzeitig, 2: prognosebasiert)
% C_bu:     nutzbare Speicherkapazität des Batteriespeichers in kWh
% dt:       Zeitschrittweite in s
% d_pv:     Anzahl der vergangenen Tage zur Ermittlung der max. PV-Leistungsabgabe
% E_b(t):   verfügbarer Batterieenergieinhalt in Wh
% E_bc:     Batterieladung (battery charge) in MWh/a
% E_bd:     Batterieentladung (battery discharge) in MWh/a
% E_ct:     abgeregelte PV-Energie (curtailment) in MWh/a
% E_gf:     Netzeinspeisung (grid feed-in) in MWh/a
% E_gs:     Netzbezug (grid supply) in MWh/a
% E_du:     direkt verbrauchte PV-Energie (direct usage) in MWh/a
% E_ld:     Haushaltsstrombedarf (load demand) in MWh/a
% E_pv:     erzeugte PV-Energie in MWh/a
% eta_batt: Wirkungsgrad des Batteriespeichers (ohne AC/DC-Wandlung)
% eta_bwr:  Wirkungsgrad des Batteriewechselrichters
% KTF:      Wetterlage-Index
% n(t):     Nachtindikator für Zeitraum ohne PV-Leistungsabgabe [false,true] 
% P_b(t):   Batterieleistung in W (positiv: Ladung, negativ: Entladung)       
% P_bc(t):  Batterieladeleistung (battery charge) in W
% P_bd(t):  Batterieentladeleistung (battery discharge) in W 
% P_bwr:    Nennleistung des Batteriewechselrichters in kW
% P_d(t):   Differenzleistung (PV-Leistung abzgl. Haushaltslast) in W
% P_du(t):  direkt verbrauchte PV-Leistung (direct usage) in W
% P_gf(t):  Netzeinseiseleistung (grid feed-in) in W
% p_gfl:    spezifische Einspeisegrenze (grid feed-in limit) in kW/kWp [0...1]
% P_gs(t):  Netzbezugsleistung (grid supply) in W
% P_ld(t):  elektrische Haushaltslast (load demand) in W
% P_pv(t):  PV-Leistungsabgabe in W
% p_pv(t):  spezifische PV-Leistungsabgabe in kW/kWp [0...1]
% p_pvf(t): prognostizierte spezifische PV-Leistungsabgabe in kW/kWp
% p_pvmax:  maximale PV-Leistungsabgabe in W
% p_pvsel:  spezifische PV-Leistungsabgabe in einem ausgewählten Zeitraum in W
% P_stc:    Nennleistung des PV-Generators unter STC-Testbedingungen in kWp
% soc(t):   Batterieladezustand (State of Charge) [0...1]
% t:        Zeitschritt
% tf_past:  Rückblick-Zeitfenster in h
% tf_prog:  Prognosehorizont in h
% time:     Zeitstempel im datenum-Format;
% v:        Abregelungsverluste 
% *f:       Prognoseswert (forecast)
% *min:     Untergrenze verschiedener Größen
% *max:     Obergrenze verschiedener Größen

%% Parametrisierung

% Hinweis: Die nachfolgend vorinitialisierten Parameter können je nach
% Speichersystem und Annahmen variieren.

dt=60; % Zeitschrittweite in s
eta_batt=0.95; % Wirkungsgrad des Lithium-Batteriespeichers (ohne AC/DC-Wandlung)
eta_bwr=0.94; % Wirkungsgrad des Batteriewechselrichters
tf_past=3; % Rückblick-Zeitfenster der PV-Prognose in h 
tf_prog=15; % Prognosehorizont der PV- und Lastprognose in h

% Hinweis: Ein Rückblick-Zeitfenster von 3 h sowie ein Zeithorizont der
% Prognosen von 15 h haben sich als sinnvoll erwiesen. Davon abweichende
% Werte können die Leistungsfähigkeit der prognosebasierten Batterieladung
% beeinträchtigen.

%% Vorinitialisierung

P_b=zeros(size(time));
soc=zeros(size(time));

%% 1. Frühzeitige Batterieladung

if bs==1; % frühzeitige Batterieladung 
%% 1.1 Batteriesimulation

% PV-Leistungsabgabe in W
P_pv=p_pv*P_stc*1000; 

% Batteriesimulation nur durchführen, wenn die Speicherkapazität größer null ist
if C_bu>0
    
% Theoretisch mögliche Batterieleistung
P_b=P_pv-P_ld; 

for t=2:length(time);
    
    % Aufruf der Unterfunktion batt_sim
    [P_b(t),soc(t)]=batt_sim(dt,P_b(t),C_bu,P_bwr,eta_batt,eta_bwr,soc(t-1));
    
end
end

%% 1.2 Auswertung der Simulationsergebnisse

% Aufruf der Unterfunktion simu_erg
[a,v,pf,eb]=simu_erg(P_pv,P_ld,P_b,P_stc,p_gfl);

end

%% 2. Prognosebasierte Batterieladung

if bs==2; % Prognosebasierte Batterieladung

%% 2.1 Erstellung der Prognosen

%% 2.1.1 PV-Prognose

% Aufruf der Unterfunktion prog4pv
p_pvf=prog4pv(time,p_pv,tf_past,tf_prog);

%% 2.1.2 Lastprognose

% Aufruf der Unterfunktion prog4ld
[P_ldf,time_f] = prog4ld(time,P_ld,tf_prog);

%% 2.2 Umsetzung der prognosebasierten Ladestrategie

% PV-Leistung in W
P_pv=p_pv*P_stc*1000; 

% PV-Leistungsprognose in W
P_pvf=p_pvf*P_stc*1000; 

% Differenzleistung
P_d=P_pv-P_ld;

% Prognose der Differenzleistung
P_df=P_pvf-P_ldf;

% Prognose der Batterieleistung (Startwert)
P_bf = 0;

% Prognose der Differenzleistung im aktuellen Zeitschritt (Startwert)
P_dfsel = 0;

% Batterieladeplanung, Ausregelung von Prognosefehlern sowie 
% Batteriesimulation nur durchführen, wenn die Speicherkapazität größer null ist
if C_bu>0

% Zeitschrittsimulation durchführen    
for t=2:length(time);
    
    %% 2.2.1 Batterieladeplanung über den Prognosehorizont
    
    % aktueller Prognosezeitschritt
    t_fsel=ceil((t)/15);
    
    % Batterieladeplanung im Intervall von 15 min durchführen, sofern
    % PV-Erzeugung vorhanden ist
    if sum(P_pv(t:min(t+15,end)))>0 && time(t)==time_f(t_fsel)
        
        % Aufruf der Unterfunktion batt_prog
        [P_bf,P_dfsel]=batt_prog(t,dt,P_df,soc,P_stc,C_bu,p_gfl,eta_batt,eta_bwr);
    
    end
            
    %% 2.2.2 Ausregelung von Prognosefehlern
    
    % Aufruf der Unterfunktion error_ctrl
    [P_b(t)]=error_ctrl(t,P_d,P_dfsel,P_bf,P_stc,P_bwr,p_gfl);
    
    %% 2.2.3 Batteriesimulation
    
    % Aufruf der Unterfunktion batt_sim
    [P_b(t),soc(t)]=batt_sim(dt,P_b(t),C_bu,P_bwr,eta_batt,eta_bwr,soc(t-1));
      
end
end

%% 2.3 Auswertung der Simulationsergebnisse

% Aufruf der Unterfunktion simu_erg
[a,v,pf,eb]=simu_erg(P_pv,P_ld,P_b,P_stc,p_gfl);

end

end

%% 3. Unterfunktionen

%% A) Unterfunktion batt_sim
function [P_b,soc]=batt_sim(dt,P_b,C_bu,P_bwr,eta_batt,eta_bwr,soc_0)

% Inhalt: Einfaches Batteriespeichermodell, in dem Wandlungsverluste durch
% konstante Verlustfaktoren berücksichtigt sind. 

% Quelle: J. Weniger: Dimensionierung und Netzintegration von
% PV-Speichersystemen. Masterarbeit, Hochschule für Technik und Wirtschaft
% HTW Berlin, 2013

% Mögliche AC-seitige Batterieleistung auf die
% Batteriewechselrichter-Nennleistung begrenzen
P_b=max(-P_bwr*1000,min(P_bwr*1000,P_b)); 

% Batteriespeicherinhalt im Zeitschritt zuvor
E_b0=soc_0*C_bu*1000; % in  Wh

if P_b>=0 %Batterieladung
    % Mögliche DC-seitige Batterieleistung unter Berücksichtigung des
    % Batteriewechselrichter-Wirkungsgrads bestimmen
    P_b=P_b*eta_bwr;
    
    % Ladung
    E_b=min(C_bu*1000, E_b0+eta_batt.*P_b.*dt/3600);
    
    % Anpassung der wirklich genutzten Leistung
    P_b=min(P_b,(C_bu*1000-E_b0)./(eta_batt*dt/3600));
    
else % Batterieentladung
    % Mögliche DC-seitige Batterieleistung unter Berücksichtigung des
    % Batteriewechselrichter-Wirkungsgrads bestimmen
    P_b=P_b/eta_bwr;
    
    % Entladung
    E_b=max(0, E_b0+P_b.*dt/3600);
    
    % Anpassung der wirklich genutzten Leistung
    P_b=max(P_b,(-E_b0)/(dt/3600));
    
end

% Realisierte AC-seitige Batterieleistung
if P_b >0 % Ladung
    P_b=P_b/eta_bwr;
else  % Entladung
    P_b=P_b*eta_bwr;
end

% Ladezustand
soc=E_b./(C_bu*1000);

end

%% B) Unterfunktion simu_erg
function [a,v,pf,eb]=simu_erg(P_pv,P_ld,P_b,P_stc,p_gfl)

% Inhalt: Berechnung der relavanten Leistungsflüsse und
% Jahresenergiebilanzen. Als Bewertungsgrößen werden zusätzlich der
% Autarkiegrad sowie die Abregelungsverluste bestimmt.

% Verbleibende Leistungswerte (power flows)
pf.P_pv=P_pv;
pf.P_ld=P_ld;
pf.P_d=P_pv-P_ld;
pf.P_du=min(P_pv,P_ld);
pf.P_bc=max(0,P_b);
pf.P_bd=abs(min(0,P_b));
pf.P_gf=max(0,min(P_stc*1000*p_gfl,pf.P_d-pf.P_bc));
pf.P_gs=abs(min(0,pf.P_d+pf.P_bd));
pf.P_ct=P_pv-pf.P_du-pf.P_bc-pf.P_gf;

% Jahresenergiesummen (energy balance)
eb.E_pv=mean(pf.P_pv)*8.76;
eb.E_ld=mean(pf.P_ld)*8.76;
eb.E_du=mean(pf.P_du)*8.76;
eb.E_bc=mean(pf.P_bc)*8.76;
eb.E_bd=mean(pf.P_bd)*8.76;
eb.E_gf=mean(pf.P_gf)*8.76;
eb.E_gs=mean(pf.P_gs)*8.76;
eb.E_ct=mean(pf.P_ct)*8.76;

% Bewertungsgrößen
a=(eb.E_du+eb.E_bd)/eb.E_ld;
v=eb.E_ct/eb.E_pv;

end

%% C) Unterfunktion prog4pv
function p_pvf=prog4pv(time,p_pv,tf_past,tf_prog)

% Inhalt: Erstellung der PV-Prognosen auf Basis der historischen Messwerte
% der PV-Leistung in Abhängigkeit vom Prognosehorizont und
% Rückblickzeitfenster.

% Quelle: J. Bergner, J. Weniger, T. Tjaden, V. Quaschning: Verbesserte
% Netzintegration von PV-Speichersystemen durch Einbindung lokal
% erstellter PV- und Lastprognosen. 30. Symposium Photovoltaische
% Solarenergie. Bad Staffelstein, 2015

% Vorinitialisierung
p_pvmax=zeros(size(time));
KTF=zeros(size(time));
p_pvf=zeros(length(time)/15,ceil(tf_prog*4));

% Tagesverlauf der maximalen PV-Leistungsabgabe aus den Messwerten der
% vergangenen 10 Tage bestimmen
for t=1440:1440:length(time)-1440
    % Anzahl der Tage, die zurückgeguckt wird (max. 10 Tage)
    d_pv=min(t/1440,10);
    % spezifische PV-Leistung während des Zeitraums
    p_pvsel=p_pv((t-d_pv*1440)+1:t);
    % maximalen Tagesverlauf der PV-Leistung bestimmen
    p_pvmax(t:t+1439,1)=max(reshape(p_pvsel,1440,d_pv),[],2);
end

% Nachtindikator (Zeitraum ohne PV-Erzeugung) bestimmen
n=p_pv<=0;

% PV-Leistung und max. PV-Leistung für Zeitraum mit PV-Erzeugung
p_pv_day=p_pv(~n);
pv_max_day=p_pvmax(~n);

% Aktuelle und maximale PV-Energie im Rückblick-Zeitfenster bestimmen
E_pv_past=zeros(sum(~n),1);
E_max=zeros(sum(~n),1);
for t=ceil(tf_past*60)+1:length(p_pv_day)
    E_pv_past(t,:)=sum(p_pv_day(t-ceil(tf_past*60):t-1,:));
    E_max(t,:)=sum(pv_max_day(t-ceil(tf_past*60):t-1,:));
end

% Verhältnis von aktueller zu maximaler PV-Energie (Wetterlage-Index KTF) im Rückblickzeitfenster berechnen
k_TF=E_pv_past./E_max;
KTF(~n)=k_TF;

% 15-Minutenmittelwerte von KTF und der maximalen PV-Leistungsabgabe p_pvmax
KTF15=mean(reshape(KTF,15,size(time,1)/15))';
p_pvmax15=mean(reshape(p_pvmax,15,size(time,1)/15))';

% Zeitreihe p_pvmax15 zweimal verketten, um zum Ende der Jahressimulation
% auf die Maximalwerte des Jahresanfangs zurückzugreifen
p_pvmax15=repmat(p_pvmax15,2,1);

% Messwertbasierte PV-Prognose erstellen: Multiplikation des aktuellen
% KTF15-Wertes mit dem Verlauf der maximalen PV-Leistung des Prognosehorizonts
for t=1:size(p_pvf,1);
    p_pvf(t,:)=max(0,min(1,KTF15(t).*p_pvmax15(t:t+ceil(tf_prog*4)-1)'));
end

% PV-Prognosen ohne Zahlenwert null setzen
p_pvf(isnan(p_pvf))=0;

end

%% D) Unterfunktion prog4ld
function [P_ldf,time_f] = prog4ld(time,P_ld,tf_prog)

% Inhalt: Erstellung der Lastprognosen auf Basis der historischen Messwerte
% der Last. Dabei werden der Mittelwert der vergangenen 15 min (aktuelle
% Persistenz) sowie das Lastprofil des vorangegangenen Tages
% (Tagespersistenz) über den Prognosehorizont unterschiedlich stark
% gewichtet. 

% Quelle: J. Bergner, J. Weniger, T. Tjaden, V. Quaschning: Verbesserte
% Netzintegration von PV-Speichersystemen durch Einbindung lokal
% erstellter PV- und Lastprognosen. 30. Symposium Photovoltaische
% Solarenergie. Bad Staffelstein, 2015

% Vorinitialisierung
P_ldf=zeros(length(time)/15,ceil(tf_prog*4));

% 15 min-Zeitstempel für die Prognosen
time_f=time(1:15:end-14);

% Lastprofil in 15-minütiger Auflösung ermitteln
P_ld15=mean(reshape(P_ld,15,size(time,1)/15))';

% Gewichtungsfaktoren für die aktuelle Persistenz und Tagespersistenz über den
% Prognosehorizont variieren
g1=1/exp(-0.1)*exp(-0.1*(1:tf_prog*4)'); %aktuelle Persistenz
g2=1-g1; %Tagespersistenz

% Messwertbasierte Lastprognose erstellen: Variable Gewichtung von
% aktueller Persistenz und Tagespersistenz über den Prognosehorizont
for t=97:length(time_f);
    P_ldf(t,:)=g1.*repmat(P_ld15(t-1),tf_prog*4,1)+g2.*P_ld(t-96:t-37);
end

end

%% E) Unterfunktion batt_prog
function [P_bf,P_dfsel]=batt_prog(t,dt,P_df,soc,P_stc,C_bu,p_gfl,eta_batt,eta_bwr)

% Inhalt: Erstellung eines Fahrplans für die Batterieleistung über den
% Prognosehorizont der PV- und Lastprognose. Hierzu wird die virtuelle
% Einspeisegrenze für den Betrachtungszeitraum soweit minimiert, dass die
% überschüssige PV-Energie oberhalb dieser Grenze den Batteriespeicher
% möglichst vollständig lädt. 

% Quelle: J. Weniger, V. Quaschning: Begrenzung der Einspeiseleistung von
% netzgekoppelten Photovoltaiksystemen mit Batteriespeichern. In: 28.
% Symposium Photovoltaische Solarenergie. Bad Staffelstein, 2013

% Weitergehende Informationen zur prognosebasierten Batterieladeplanung: 
% J. Bergner: Untersuchungen zu prognosebasierten Betriebsstrategien für
% PV-Speichersysteme. Berlin, Hochschule für Technik und Wirtschaft
% Berlin, Bachelorthesis, 2014

% aktueller Prognosezeitschritt
t_fsel=ceil((t)/15);

% aktuelle Differenzleistungsprognose auswählen
P_dfsel=double(P_df(t_fsel,:)');

% Batterieladezustand und Batterieinhalt im Zeitschritt zuvor
soc_0=soc(t-1);
E_b0=soc_0*C_bu*1000;

% Vorbereitung der Bestimmung der aktuellen virtuellen
% Einspeisegrenze durch Variation der virtuellen Einspeisegrenze in
% 0,01 kW/kWp-Schritten
p_gflvir=repmat((0:0.01:p_gfl),size(P_dfsel,1),1);

% Prognostizierte überschüssige PV-Leistung
P_sf=repmat(max(0,P_dfsel),1,size(p_gflvir,2));

% Idendifikation der minimalen virtuellen Einspeisegrenze, die über
% den Prognosehorizont eingehalten werden soll: Dabei soll die
% Energiemenge oberhalb dieser Grenze ausreichend sein, um den
% Batteriespeicher über den Prognosehorizont möglichst vollständig
% zu laden.
[~,idx]=min(abs(sum(max(0,(P_sf-p_gflvir*P_stc*1000)).*eta_batt.*eta_bwr.*dt*15/3600)-(C_bu*1000-E_b0)));
p_gflvir=p_gflvir(1,idx); % kW/kWp

% Batterieladeleistung über Prognosehorizont aus virtueller
% Einspeisegrenze ableiten
P_bcf=max(0,P_dfsel-p_gflvir*P_stc*1000); %W

% Batterieleistung aus Batterieladeleistung und Differenzleistung
% über Prognosehorizont bestimmen
P_bf=round(min(P_bcf,P_dfsel));

end

%% F) Unterfunktion error_ctrl
function [P_b]=error_ctrl(t,P_d,P_dfsel,P_bf,P_stc,P_bwr,p_gfl)

% Inhalt: Anpassung der geplanten Batterieleistung zum Ausgleich von
% Prognosefehlern. Hierzu wird die prognostizierte Ladeleistung durch eine
% Regelung um die Differenz zwischen den Prognose- und Messwerten
% korrigiert.

% Quelle: J. Weniger, J. Bergner, V. Quaschning: Integration of PV power
% and load forecasts into the operation of residential PV battery systems.
% In: 4th Solar Integration Workshop. Berlin, 2014

if P_d(t)>0 % (Leistungsüberschuss)
    % Anpassung der Ladeleistung, wenn die aktuelle Differenzleistung größer
    % null und überschüssige PV-Leistung vorhanden ist
    %
    % Batterieladeleistung wird angepasst, wenn eine der folgenden
    % Bedingungen erfüllt wird:
    %
    % (1) Die für den aktuellen Zeitschritt prognostizierte
    % Batterieleistung ist ungleich null
    % (2) Die aktuelle Differenzleistung ist größer als die max.
    % prognostizierte Einspeiseleistung (virtuelle Einspeisegrenze)
    % während des Prognosehorizonts
    % (3) Die aktuelle Differenzleistung übersteigt die max. zulässige
    % Einspeisegrenze
    
    if P_bf(1)~=0 || P_d(t)>max(P_dfsel-P_bf) || P_d(t)>p_gfl*P_stc*1000
        % Aktuelle Ladeleistung um die Differenz zwischen der aktuellen
        % Differenzleistung P_d(t) und der prognostizierten Differenzleistung
        % P_dfsel(1) korrigieren. Dadurch wird gewährleistet, dass die
        % zuvor ermittelte virtuelle Einspeisegrenze eingehalten wird
        P_b=max(0,P_bf(1)+P_d(t)-P_dfsel(1));
        
        % Ladeleistung auf die Nennleistung des Batteriewechselrichters
        % begrenzen
        P_b=min(P_bwr*1000,P_b);
        
    else
        % Wenn keine der zuvor aufgeführten Bedingungen erfüllt wird, soll
        % die aktuelle Batterieladeleistung auf null gesetzt werden.
        % Dadurch wird eine stufige Anpassung der Einspeiseleistung
        % verhindert.
        P_b=0;
    end
    
else % P_d(t)<0 (Leistungsdefizit)
    % Entladeleistung gemäß Leistungsdefizit anpassen und auf die Nennleistung des
    % Batteriewechselrichters begrenzen.
    P_b=max(-P_bwr*1000,P_d(t));
end
end

