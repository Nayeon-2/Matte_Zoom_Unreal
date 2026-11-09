#include "ZoomCameraActor.h"

#include "CineCameraComponent.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/KismetMaterialLibrary.h"
#include "Materials/MaterialParameterCollection.h"
#include "HAL/PlatformTime.h"
#include "TextureResource.h"
#include "UnrealClient.h"

DEFINE_LOG_CATEGORY_STATIC(LogZoomCamera, Log, All);

namespace ZoomCode
{
	constexpr int32 Block = 4;           // block size in pixels (matches Python CODE_BLOCK)
	constexpr int32 DistanceBlock = 0;
	constexpr int32 SignatureBlock = 1;
	constexpr int32 ZoomBlock = 5;
	constexpr double ScaleMax = 256.0;   // matches Python ZOOM_SCALE_MAX
}

AZoomCameraActor::AZoomCameraActor(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	PrimaryActorTick.bCanEverTick = true;
	// After the Spout receiver components have copied this frame into the render target.
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;
}

void AZoomCameraActor::BeginPlay()
{
	Super::BeginPlay();
	CurrentCue = StartCue;
	bCueBlending = false;
}

void AZoomCameraActor::SetPersonCue(EPersonDepthCue NewCue)
{
	CurrentCue = NewCue;
	CueFromDepth = CurrentPersonDepth;
	CueStartTime = FPlatformTime::Seconds();
	bCueBlending = true;
	static const TCHAR* Names[] = { TEXT("Auto"), TEXT("Front"), TEXT("Back") };
	UE_LOG(LogZoomCamera, Log, TEXT("%s: person cue -> %s"), *GetActorNameOrLabel(), Names[uint8(NewCue)]);
}

void AZoomCameraActor::PollCueKeys()
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC)
	{
		return;
	}
	if (PC->WasInputKeyJustPressed(FrontKey))
	{
		SetPersonCue(EPersonDepthCue::Front);
	}
	else if (PC->WasInputKeyJustPressed(BackKey))
	{
		SetPersonCue(EPersonDepthCue::Back);
	}
	else if (PC->WasInputKeyJustPressed(AutoKey))
	{
		SetPersonCue(EPersonDepthCue::Auto);
	}
}

float AZoomCameraActor::GetHorizontalFOV() const
{
	const UCineCameraComponent* Cine = GetCineCameraComponent();
	return Cine ? Cine->GetHorizontalFieldOfView() : 0.0f;
}

bool AZoomCameraActor::ReadCode(FZoomCodeFrame& Out)
{
	Out = FZoomCodeFrame();
	if (!CodeTexture)
	{
		return false;
	}
	FTextureRenderTargetResource* Res = CodeTexture->GameThread_GetRenderTargetResource();
	const int32 W = (ZoomCode::ZoomBlock + 1) * ZoomCode::Block;
	if (!Res || int32(Res->GetSizeX()) < W)
	{
		return false;
	}

	// One small synchronous read of the code row: same frame as the plates, no extra latency.
	const double T0 = FPlatformTime::Seconds();
	TArray<FColor> Px;
	FReadSurfaceDataFlags Flags(RCM_UNorm);
	Flags.SetLinearToGamma(false);
	const bool bRead = Res->ReadPixels(Px, Flags, FIntRect(0, 0, W, ZoomCode::Block));
	ReadbackMs = float((FPlatformTime::Seconds() - T0) * 1000.0);
	if (!bRead || Px.Num() < W * ZoomCode::Block)
	{
		return false;
	}

	// Sample the middle of each 4x4 block. R = high byte, G = low byte, B = valid flag.
	auto At = [&](int32 BlockIndex) { return Px[1 * W + BlockIndex * ZoomCode::Block + 1]; };
	auto Value16 = [](const FColor& C) { return (uint32(C.R) << 8) | uint32(C.G); };
	const FColor Sig = At(ZoomCode::SignatureBlock);
	if (!(Sig.G > 200 && Sig.R < 50 && Sig.B < 50))
	{
		return false;
	}
	const FColor Z = At(ZoomCode::ZoomBlock);
	if (Z.B >= 128)
	{
		Out.bZoomValid = true;
		Out.Scale = float(FMath::Exp(double(Value16(Z)) / 65535.0 * FMath::Loge(ZoomCode::ScaleMax)));
	}
	const FColor D = At(ZoomCode::DistanceBlock);
	if (D.B >= 128)
	{
		Out.bDistanceValid = true;
		Out.DistanceM = float(Value16(D)) / 1000.0f;
	}
	return true;
}

void AZoomCameraActor::ApplyScale(float Scale)
{
	CurrentScale = FMath::Clamp(Scale, 1.0f, float(ZoomCode::ScaleMax));
	if (UCineCameraComponent* Cine = GetCineCameraComponent())
	{
		Cine->SetCurrentFocalLength(WideFocalLength * CurrentScale);
	}
	if (bFitPlates)
	{
		FitPlates();
	}
}

void AZoomCameraActor::ApplyPersonDepth(float Depth)
{
	CurrentPersonDepth = FMath::Clamp(Depth, MinPersonDepth, MaxPersonDepth);
	TArray<AActor*> Attached;
	GetAttachedActors(Attached);
	for (AActor* Child : Attached)
	{
		USceneComponent* Root = Child ? Child->GetRootComponent() : nullptr;
		if (Root && Child->ActorHasTag(PersonPlateTag))
		{
			FVector Loc = Root->GetRelativeLocation();
			if (!FMath::IsNearlyEqual(Loc.X, CurrentPersonDepth, 0.01))
			{
				Loc.X = CurrentPersonDepth;
				Root->SetRelativeLocation(Loc);
			}
		}
	}
}

void AZoomCameraActor::FitPlates()
{
	const float HalfTan = FMath::Tan(FMath::DegreesToRadians(GetHorizontalFOV() * 0.5f));
	const UCineCameraComponent* Cine = GetCineCameraComponent();
	const float Aspect = (Cine && Cine->Filmback.SensorHeight > 0.f)
		? Cine->Filmback.SensorWidth / Cine->Filmback.SensorHeight : 16.f / 9.f;

	TArray<AActor*> Attached;
	GetAttachedActors(Attached);
	for (AActor* Child : Attached)
	{
		USceneComponent* Root = Child ? Child->GetRootComponent() : nullptr;
		if (!Root || !Child->ActorHasTag(PlateTag))
		{
			continue;
		}
		const float Dist = Root->GetRelativeLocation().X;
		const float Width = 2.f * Dist * HalfTan;
		const FVector NewScale(Width / PlateMeshSize, Width / Aspect / PlateMeshSize, 1.0);
		if (!Root->GetRelativeScale3D().Equals(NewScale, 1e-4))
		{
			Root->SetRelativeScale3D(NewScale);
		}
	}
}

void AZoomCameraActor::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	FZoomCodeFrame Code;
	bCodeValid = bUseCode && ReadCode(Code);

	// Person depth first: FitPlates (inside ApplyScale) sizes the plate at its new distance.
	bDistanceValid = bCodeValid && Code.bDistanceValid;
	if (bDistanceValid)
	{
		PersonDistanceM = Code.DistanceM;
		bHasDistance = true;
	}
	if (bEnableCueKeys)
	{
		PollCueKeys();
	}
	if (bUsePersonDepth)
	{
		const float AutoDepth = bHasDistance ? DepthOffset + PersonDistanceM * DepthPerMeter : DefaultPersonDepth;
		const float Target = CurrentCue == EPersonDepthCue::Front ? CueFrontDepth
			: CurrentCue == EPersonDepthCue::Back ? CueBackDepth : AutoDepth;
		float Depth = Target;
		if (bCueBlending)
		{
			const float K = FMath::SmoothStep(0.0f, 1.0f, float((FPlatformTime::Seconds() - CueStartTime) / CueMoveTime));
			Depth = FMath::Lerp(CueFromDepth, Target, K);
			bCueBlending = K < 1.0f;
		}
		ApplyPersonDepth(Depth);
	}
	if (DepthParameters)
	{
		UKismetMaterialLibrary::SetScalarParameterValue(this, DepthParameters, TEXT("PersonDepth"), CurrentPersonDepth);
		UKismetMaterialLibrary::SetScalarParameterValue(this, DepthParameters, TEXT("PassBand"), PassBand);
	}

	float Scale = ManualScale;
	if (bUseCode)
	{
		Scale = (bCodeValid && Code.bZoomValid) ? Code.Scale : CurrentScale;   // hold the last value
	}
	ApplyScale(Scale);

	const double Now = FPlatformTime::Seconds();
	if (Now - LastLogTime > 5.0)
	{
		LastLogTime = Now;
		UE_LOG(LogZoomCamera, Log,
			TEXT("%s: scale x%.2f focal %.1f mm hfov %.2f deg | person %.2f m -> %.0f cm | code=%s readback %.2f ms"),
			*GetActorNameOrLabel(), CurrentScale, WideFocalLength * CurrentScale, GetHorizontalFOV(),
			PersonDistanceM, CurrentPersonDepth, bCodeValid ? TEXT("ok") : TEXT("-"), ReadbackMs);
	}
}
